import base64
import csv
import email
import io
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, authenticity, authstats, config, datasets, db, importer, jobs
from .categories import BY_KEY, CATEGORIES, SEVERITY_LABELS, VERIFIED_LABELS
from .junk import DOC_COND, DOC_GROUPS, MAIL_GROUPS, MAIL_KEYS

STATIC = os.path.join(os.path.dirname(__file__), "static")
STATE = {"lan": False, "password": "", "last_ping": None}          # wird von der Kommandozeile gesetzt (hexane-desk serve --lan)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

@asynccontextmanager
async def lifespan(_app):
    config.ensure_lists_templates()
    db.init()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def raw_root() -> str:
    """Wurzelordner des Datensatzes (alle Quellpfade im Index sind relativ dazu)."""
    root = config.data_root()
    if not root:
        raise HTTPException(409, "Es ist noch kein Datenordner gewählt.")
    return str(root)


def _host_of(request: Request) -> str:
    h = request.headers.get("host", "")
    if h.startswith("["):                                   # IPv6: [::1]:8480
        return h[1:].split("]")[0].lower()
    return (h.rsplit(":", 1)[0] if ":" in h else h).lower()


@app.middleware("http")
async def guard(request: Request, call_next):
    """Schützt die sensiblen Daten: nur lokale Hostnamen (gegen DNS-Rebinding) und Zugriffstoken statt offener Seite."""
    host = _host_of(request)
    if not STATE["lan"] and host not in LOCAL_HOSTS:
        return Response("Host nicht erlaubt", status_code=403)
    cookie = request.cookies.get("hexane_token", "")
    if not secrets.compare_digest(cookie, config.TOKEN):
        t = request.query_params.get("t", "")
        if t and secrets.compare_digest(t, config.TOKEN):          # erster Aufruf mit Link aus dem Programm
            rest = "&".join(f"{k}={v}" for k, v in request.query_params.items() if k != "t")
            resp = RedirectResponse(request.url.path + ("?" + rest if rest else ""), status_code=303)
            resp.set_cookie("hexane_token", config.TOKEN, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
            return resp
        ok = False
        if STATE["password"]:                                       # LAN-Betrieb: Passwort
            h = request.headers.get("authorization", "")
            if h.startswith("Basic "):
                try:
                    ok = secrets.compare_digest(base64.b64decode(h[6:]).decode().partition(":")[2], STATE["password"])
                except Exception:
                    ok = False
            if not ok:
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="hexane-desk"'})
        else:
            return Response("Bitte den Link aus dem Programm verwenden (er enthält das Zugriffstoken).", status_code=401)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"            # Oberfläche nach Programmupdates nie veraltet aus dem Browser-Cache
    return resp


OPS = {"von": "from", "from": "from", "an": "to", "to": "to", "betreff": "subject", "subject": "subject",
       "hat": "has", "has": "has", "vor": "before", "before": "before", "nach": "after", "after": "after",
       "ordner": "folder", "folder": "folder"}
QTOKEN = re.compile(r'(?:(\w+):)?(?:"([^"]*)"|(\S+))')


def fq(term: str) -> str:
    t = '"' + term.replace('"', '""') + '"'
    return t if re.search(r"\s", term) else t + "*"


def fq_or(col: str, val: str) -> str:
    """Spaltenfilter; mehrere Werte mit | ergeben ODER (z. B. von:"a@x.de|b@y.de")."""
    parts = [p.strip() for p in val.split("|") if p.strip()]
    if len(parts) > 1:
        return f"{col} : (" + " OR ".join(fq(p) for p in parts) + ")"
    return f"{col} : {fq(val)}"


def day_ts(s: str):
    try:
        return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def like_prefix(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def parse_query(q: str):
    fts, where, args = [], [], []
    for m in QTOKEN.finditer(q or ""):
        key = (m.group(1) or "").lower()
        val = m.group(2) if m.group(2) is not None else m.group(3)
        if key and key not in OPS:
            key, val = "", m.group(0).strip('"')
        op = OPS.get(key, "")
        val = (val or "").strip()
        if not val:
            continue
        if op == "from":
            fts.append(fq_or("from_text", val))
        elif op == "to":
            fts.append(fq_or("to_text", val))
        elif op == "subject":
            fts.append(fq_or("subject", val))
        elif op == "has":
            if val.lower() in ("anhang", "attachment", "attachments"):
                where.append("m.att_count > 0")
        elif op in ("before", "after"):
            ts = day_ts(val)
            if ts is not None:
                where.append("m.date_ts < ?" if op == "before" else "m.date_ts >= ?")
                args.append(ts)
        elif op == "folder":
            where.append("m.folder LIKE ? ESCAPE '\\'")
            args.append(like_prefix(val))
        else:
            fts.append(fq(val))
    return fts, where, args


@app.get("/api/ping")
def ping():
    """Lebenszeichen der geöffneten Seite (der Starter beendet das Programm, wenn sie ausbleiben)."""
    STATE["last_ping"] = time.time()
    return {"ok": True}


@app.get("/api/stats")
def stats():
    conn = db.connect()
    return {"messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]}


@app.get("/api/folders")
def folders():
    conn = db.connect()
    rows = conn.execute("SELECT folder, COUNT(*) AS n FROM messages GROUP BY folder ORDER BY folder").fetchall()
    return [{"folder": r["folder"], "count": r["n"]} for r in rows]


@app.get("/api/messages")
def messages(q: str = "", folder: str = "", sort: str = "date_desc", cat: str = "", hide: str = "",
             offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    fts, where, args = parse_query(q)
    cc = cat_clause(cat)
    if cc:
        fts.append(cc)
    hc, hargs = mail_hide_clause(hide)
    if hc:
        where.append(hc)
        args += hargs
    if folder:
        where.append("(m.folder = ? OR m.folder LIKE ? ESCAPE '\\')")
        args += [folder, like_prefix(folder.rstrip("/") + "/")]

    cols = ("m.id, m.folder, m.from_name, m.from_addr, m.subject, m.date_ts, m.preview, m.att_count, "
            "(SELECT severity FROM marks mk WHERE mk.kind = 'mail' AND mk.src = m.source_path "
            "AND mk.key = COALESCE(m.mbox_key, '')) AS sev")
    if fts:
        cols += ", snippet(messages_fts, 3, char(1), char(2), '…', 14) AS snip"
        frm = "FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid"
        where.insert(0, "messages_fts MATCH ?")
        args.insert(0, " AND ".join(fts))
    else:
        cols += ", NULL AS snip"
        frm = "FROM messages m"

    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    order = {"date_asc": "m.date_ts ASC", "rank": "rank" if fts else "m.date_ts DESC"}.get(sort, "m.date_ts DESC")

    conn = db.connect()
    try:
        total = conn.execute(f"SELECT COUNT(*) {frm} {wsql}", args).fetchone()[0]
        rows = conn.execute(f"SELECT {cols} {frm} {wsql} ORDER BY {order} LIMIT ? OFFSET ?",
                            args + [limit, offset]).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(400, f"Ungültige Suche: {e}")
    return {"total": total, "items": [dict(r) for r in rows]}


@app.get("/api/messages/{mid}")
def message(mid: int):
    conn = db.connect()
    r = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    atts = conn.execute("SELECT id, filename, content_type, size FROM attachments "
                        "WHERE message_id = ? ORDER BY part_index", (mid,)).fetchall()
    thread = []
    if r["thread_id"]:
        thread = [dict(t) for t in conn.execute(
            "SELECT id, subject, from_name, from_addr, date_ts FROM messages "
            "WHERE thread_id = ? ORDER BY date_ts LIMIT 200", (r["thread_id"],))]
    d = {k: r[k] for k in ("id", "folder", "from_name", "from_addr", "to_addrs", "cc_addrs",
                           "subject", "date_ts", "has_html", "size", "source_path")}
    d["body_text"] = (r["body_text"] or "")[:500_000]
    d["attachments"] = [dict(a) for a in atts]
    d["thread"] = thread
    return d


def _raw(mid: int):
    conn = db.connect()
    r = conn.execute("SELECT source_path, mbox_key FROM messages WHERE id = ?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    try:
        return importer.load_raw(r["source_path"], r["mbox_key"], raw_root())
    except (OSError, ValueError, KeyError):
        raise HTTPException(404, "Originaldatei nicht lesbar")


@app.get("/api/messages/{mid}/html")
def message_html(mid: int):
    msg = _raw(mid)
    part = msg.get_body(preferencelist=("html",))
    if part is None:
        raise HTTPException(404, "Keine HTML-Version")
    page = ('<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
            '<base target="_blank"><style>body{font:14px sans-serif;margin:12px;overflow-wrap:anywhere}</style>'
            + part.get_content())
    return HTMLResponse(page, headers={
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"})


INLINE_OK = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@app.get("/api/attachments/{aid}")
def attachment(aid: int, inline: int = 0):
    conn = db.connect()
    a = conn.execute("SELECT message_id, part_index, filename, content_type FROM attachments WHERE id = ?",
                     (aid,)).fetchone()
    if not a:
        raise HTTPException(404)
    parts = list(_raw(a["message_id"]).iter_attachments())
    if a["part_index"] >= len(parts):
        raise HTTPException(404)
    data = parts[a["part_index"]].get_payload(decode=True) or b""
    name = (a["filename"] or f"anhang-{aid}").replace("\r", "").replace("\n", "")
    show = bool(inline) and a["content_type"] in INLINE_OK
    return Response(data, media_type=a["content_type"] if show else "application/octet-stream", headers={
        "Content-Disposition": f"{'inline' if show else 'attachment'}; filename*=UTF-8''{quote(name)}",
        "Content-Security-Policy": "sandbox"})


# ---------- Rohheader (Echtheitsprüfung) ----------

SHOW_HEADERS = ["From", "Sender", "Reply-To", "Return-Path", "To", "Cc", "Delivered-To", "X-Original-To", "Date",
                "Message-ID", "Subject", "List-Id", "X-Mailer", "User-Agent", "X-Originating-IP"]


def _dom(s: str) -> str:
    m = re.search(r"@([A-Za-z0-9.-]+)", s or "")
    return m.group(1).lower().rstrip(".") if m else ""


@app.get("/api/messages/{mid}/headers")
def message_headers(mid: int):
    """Header der Original-Mail und eine einfache Einordnung. Es wird NICHT kryptografisch geprüft."""
    conn = db.connect()
    r = conn.execute("SELECT source_path, mbox_key FROM messages WHERE id = ?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    try:
        data = importer.load_raw_bytes(r["source_path"], r["mbox_key"], raw_root())
    except (OSError, ValueError):
        raise HTTPException(404, "Originaldatei nicht lesbar")
    head = re.split(rb"\r?\n\r?\n", data, maxsplit=1)[0]
    msg = email.message_from_bytes(head)                     # toleranter Parser
    hv = lambda name: [" ".join(str(v).split()) for v in msg.get_all(name, [])]

    auth = hv("Authentication-Results") + hv("ARC-Authentication-Results")
    verdicts = sorted({f"{k.lower()}={v.lower()}" for a in auth for k, v in re.findall(r"\b(spf|dkim|dmarc)\s*=\s*(\w+)", a, re.I)})
    dkim = []
    for sig in hv("DKIM-Signature"):
        d, s = re.search(r"\bd=([^;\s]+)", sig), re.search(r"\bs=([^;\s]+)", sig)
        dkim.append({"domain": d.group(1).lower() if d else "", "selector": s.group(1) if s else ""})
    from_dom = _dom((hv("From") or [""])[0])
    ret_dom = _dom((hv("Return-Path") or [""])[0])
    received = hv("Received")

    hints = []
    aligned = None
    if not dkim:
        hints.append("Keine DKIM-Signatur in den Headern: Die Herkunft lässt sich nicht kryptografisch belegen.")
    else:
        aligned = any(from_dom and (from_dom == x["domain"] or from_dom.endswith("." + x["domain"]) or
                                    x["domain"].endswith("." + from_dom)) for x in dkim)
        if not aligned:
            hints.append("Die DKIM-Domain passt nicht zur Domain des Absenders (From). Das kann bei Diensten und Listen normal sein.")
    if from_dom and ret_dom and from_dom != ret_dom and not ret_dom.endswith("." + from_dom) and not from_dom.endswith("." + ret_dom):
        hints.append(f"Absender (From: {from_dom}) und Envelope-Absender (Return-Path: {ret_dom}) weichen ab.")
    try:
        d_date = parsedate_to_datetime(hv("Date")[0])
        r_date = parsedate_to_datetime(received[0].rsplit(";", 1)[1].strip())
        diff = abs((r_date - d_date).total_seconds()) / 86400
        if diff > 2:
            hints.append(f"Das Datum der Mail (Date) weicht um {diff:.0f} Tage vom obersten Received-Eintrag ab.")
    except Exception:
        pass
    if not received:
        hints.append("Keine Received-Zeilen: Der Zustellweg lässt sich nicht nachvollziehen.")

    return {"raw": head.decode("utf-8", "replace")[:60000],
            "fields": [{"name": n, "values": hv(n)} for n in SHOW_HEADERS if hv(n)],
            "auth": {"results": auth, "verdicts": verdicts}, "dkim": dkim, "dkim_aligned": aligned,
            "received": received, "hints": hints,
            "note": "Header lassen sich fälschen, und Signaturen älterer Mails können heute nicht mehr geprüft werden "
                    "(Schlüssel rotiert). Dieser Abschnitt zeigt nur, was in der Datei steht."}


@app.get("/api/messages/{mid}/authenticity")
def message_authenticity(mid: int, online: int = 0, fmt: str = ""):
    """Echtheitsbericht (Indizien, keine Beweise). online=1 holt DKIM-Schlüssel per DNS und braucht die Zustimmung des Nutzers."""
    if online and not config.settings().dns_consent:
        raise HTTPException(403, "Für die Online-Prüfung fehlt die Zustimmung (Einstellung dns_consent).")
    conn = db.connect()
    r = conn.execute("SELECT source_path, mbox_key, thread_id, subject FROM messages WHERE id = ?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404)
    try:
        from_line, data = importer.load_full(r["source_path"], r["mbox_key"], raw_root())
    except (OSError, ValueError) as e:
        raise HTTPException(404, f"Originaldatei nicht lesbar ({e})")
    rep = authenticity.analyze(data, from_line, conn, mid, r["thread_id"], online=bool(online),
                               location={"file": r["source_path"], "key": r["mbox_key"]})
    if fmt == "md":
        return Response(authenticity.to_markdown(rep, r["subject"] or ""), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="echtheitsbericht-{mid}.md"'})
    import importlib.util
    rep["online_possible"] = importlib.util.find_spec("dkim") is not None
    rep["dns_consent"] = config.settings().dns_consent
    return rep


@app.get("/api/forensics/stats")
def forensics_stats():
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM auth_stats LIMIT 1").fetchone():
        return {"folders": [], "total": {}}
    return authstats.summary(conn)


# ---------- Spenden-Übersicht (ohne Namen) ----------

BUCKETS = [(0, 1000, "unter 10 €"), (1000, 2500, "10 bis 24 €"), (2500, 5000, "25 bis 49 €"), (5000, 10000, "50 bis 99 €"),
           (10000, 25000, "100 bis 249 €"), (25000, 50000, "250 bis 499 €"), (50000, 100000, "500 bis 999 €"),
           (100000, 10 ** 12, "1.000 € und mehr")]


@app.get("/api/donations/summary")
def donations_summary():
    conn = db.connect()
    total = conn.execute("SELECT COUNT(*) FROM donations").fetchone()[0]
    if not total:
        return {"total": 0}
    how = {r[0]: r[1] for r in conn.execute("SELECT how, COUNT(*) FROM donations GROUP BY how")}
    cents = [r[0] for r in conn.execute("SELECT cents FROM donations WHERE cents IS NOT NULL")]
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]
    return {
        "total": total, "parsed": len(cents), "how": how, "sum_cents": sum(cents),
        "first_ts": conn.execute("SELECT MIN(ts) FROM donations").fetchone()[0],
        "last_ts": conn.execute("SELECT MAX(ts) FROM donations").fetchone()[0],
        "years": q("SELECT strftime('%Y', ts, 'unixepoch') AS year, COUNT(*) AS n, COALESCE(SUM(cents), 0) AS sum "
                   "FROM donations WHERE ts IS NOT NULL GROUP BY year ORDER BY year"),
        "monthly": q("SELECT strftime('%Y-%m', ts, 'unixepoch') AS month, COUNT(*) AS n, COALESCE(SUM(cents), 0) AS sum "
                     "FROM donations WHERE ts IS NOT NULL GROUP BY month ORDER BY month"),
        "buckets": [{"label": lab, "n": sum(1 for c in cents if lo <= c < hi), "sum": sum(c for c in cents if lo <= c < hi)}
                    for lo, hi, lab in BUCKETS],
        "top_amounts": q("SELECT cents, COUNT(*) AS n FROM donations WHERE cents IS NOT NULL GROUP BY cents "
                         "ORDER BY n DESC LIMIT 12"),
        "top_days": q("SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day, COUNT(*) AS n, COALESCE(SUM(cents), 0) AS sum "
                      "FROM donations WHERE ts IS NOT NULL GROUP BY day ORDER BY n DESC LIMIT 10"),
    }


# ---------- Recherche: Kategorien und Markierungen ----------

def cat_clause(cat: str):
    """FTS-Ausdruck einer Kategorie: alle Begriffe mit ODER verknüpft (Wortanfänge bzw. Phrasen)."""
    c = BY_KEY.get(cat)
    return "(" + " OR ".join(fq(t) for t in c["terms"]) + ")" if c else None


@app.get("/api/categories")
def categories():
    return [{"key": c["key"], "label": c["label"], "desc": c["desc"]} for c in CATEGORIES]


def _mark_item(conn, kind: str, iid: int) -> dict:
    """Quelle und Titel eines Elements. Markierungen hängen an Quelldatei/Schlüssel, nicht an der internen id."""
    if kind == "mail":
        r = conn.execute("SELECT source_path, mbox_key, subject, from_name, from_addr, date_ts FROM messages "
                         "WHERE id = ?", (iid,)).fetchone()
        if not r:
            raise HTTPException(404)
        who = r["from_name"] or r["from_addr"] or ""
        day = datetime.fromtimestamp(r["date_ts"], timezone.utc).strftime("%Y-%m-%d") if r["date_ts"] else ""
        return {"src": r["source_path"], "key": r["mbox_key"] or "", "title": r["subject"] or "(kein Betreff)",
                "subtitle": f"{who} · {day}".strip(" ·")}
    if kind == "doc":
        r = conn.execute("SELECT path, name, substr(text, 1, 400) AS head, doc_date FROM documents WHERE id = ?",
                         (iid,)).fetchone()
        if not r:
            raise HTTPException(404)
        return {"src": r["path"], "key": "", "title": doc_title(r["head"]) or r["name"],
                "subtitle": r["name"] + (f" · {r['doc_date']}" if r["doc_date"] else "")}
    raise HTTPException(404)


def _mark_row(r) -> dict:
    cat = r["category"] or ""
    return {"id": r["id"], "kind": r["kind"], "severity": r["severity"], "category": cat,
            "category_label": BY_KEY[cat]["label"] if cat in BY_KEY else "", "note": r["note"] or "",
            "verified": r["verified"], "title": r["title"], "subtitle": r["subtitle"], "updated_ts": r["updated_ts"]}


@app.get("/api/marks/facets")
def marks_facets():
    conn = db.connect()
    return {
        "total": conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0],
        "severity": [{"severity": r[0], "label": SEVERITY_LABELS.get(r[0], ""), "count": r[1]} for r in
                     conn.execute("SELECT severity, COUNT(*) FROM marks GROUP BY severity ORDER BY severity DESC")],
        "categories": [{"key": r[0] or "", "label": BY_KEY[r[0]]["label"] if r[0] in BY_KEY else "ohne Kategorie",
                        "count": r[1]} for r in
                       conn.execute("SELECT category, COUNT(*) FROM marks GROUP BY category ORDER BY COUNT(*) DESC")],
        "verified": [{"verified": r[0], "label": VERIFIED_LABELS.get(r[0], ""), "count": r[1]} for r in
                     conn.execute("SELECT verified, COUNT(*) FROM marks GROUP BY verified ORDER BY verified")],
    }


def _marks_where(q: str, folder: str):
    where, args = [], []
    try:
        if folder.startswith("sev:"):
            where.append("severity = ?")
            args.append(int(folder[4:]))
        elif folder.startswith("cat:"):
            where.append("COALESCE(category, '') = ?")
            args.append(folder[4:])
        elif folder.startswith("ver:"):
            where.append("verified = ?")
            args.append(int(folder[4:]))
    except ValueError:
        raise HTTPException(400, "Ungültiger Filter")
    for t in (q or "").split():
        where.append("(title LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\' OR subtitle LIKE ? ESCAPE '\\')")
        args += ["%" + like_prefix(t)] * 3
    return ("WHERE " + " AND ".join(where)) if where else "", args


MARK_ORDER = "severity DESC, verified DESC, updated_ts DESC"


def _resolve(conn, r):
    """Aktuelle interne id des markierten Elements (None, wenn es im Index nicht mehr existiert)."""
    if r["kind"] == "mail":
        x = conn.execute("SELECT id FROM messages WHERE source_path = ? AND COALESCE(mbox_key, '') = ?",
                         (r["src"], r["key"])).fetchone()
    else:
        x = conn.execute("SELECT id FROM documents WHERE path = ?", (r["src"],)).fetchone()
    return x["id"] if x else None


@app.get("/api/marks")
def marks_list(q: str = "", folder: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    wsql, args = _marks_where(q, folder)
    conn = db.connect()
    total = conn.execute(f"SELECT COUNT(*) FROM marks {wsql}", args).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM marks {wsql} ORDER BY {MARK_ORDER} LIMIT ? OFFSET ?",
                        args + [limit, offset]).fetchall()
    return {"total": total, "items": [{**_mark_row(r), "item_id": _resolve(conn, r)} for r in rows]}


@app.get("/api/marks/export")
def marks_export(fmt: str = "md", limit: int = Query(100, ge=1, le=1000), min_sev: int = Query(1, alias="min", ge=1, le=5)):
    conn = db.connect()
    rows = conn.execute(f"SELECT * FROM marks WHERE severity >= ? ORDER BY {MARK_ORDER} LIMIT ?",
                        (min_sev, limit)).fetchall()
    ref = lambda r: r["src"] + (f"#{r['key']}" if r["key"] else "")
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["rang", "kritikalitaet", "kategorie", "pruefstatus", "typ", "titel", "absender_datum", "quelle", "notiz"])
        for i, r in enumerate(rows, 1):
            m = _mark_row(r)
            w.writerow([i, r["severity"], m["category_label"], VERIFIED_LABELS.get(r["verified"], ""), r["kind"],
                        r["title"], r["subtitle"], ref(r), m["note"]])
        return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="top-{limit}.csv"'})
    lines = [f"# Recherche: höchste Kritikalität (Top {len(rows)})", "",
             f"Stand: {time.strftime('%Y-%m-%d')} · Skala: 5 kritisch · 4 schwerwiegend · 3 gravierend · 2 bedenklich · 1 auffällig",
             "Alle Einträge sind manuelle Bewertungen. Prüfstatus beachten; ungeprüfte Einträge sind keine Belege.", ""]
    for i, r in enumerate(rows, 1):
        m = _mark_row(r)
        lines += [f"## {i}. [{r['severity']} {SEVERITY_LABELS.get(r['severity'], '')}] {r['title']}",
                  f"- Kategorie: {m['category_label'] or '–'}",
                  f"- Prüfstatus: {VERIFIED_LABELS.get(r['verified'], '')}",
                  f"- {'Mail' if r['kind'] == 'mail' else 'Dokument'}: {r['subtitle']}",
                  f"- Quelle: `{ref(r)}`"]
        if m["note"]:
            lines.append(f"- Notiz: {m['note']}")
        lines.append("")
    return Response("\n".join(lines), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="top-{limit}.md"'})


@app.get("/api/marks/{kind}/{iid}")
def mark_get(kind: str, iid: int):
    conn = db.connect()
    it = _mark_item(conn, kind, iid)
    r = conn.execute("SELECT * FROM marks WHERE kind = ? AND src = ? AND key = ?", (kind, it["src"], it["key"])).fetchone()
    return {"mark": _mark_row(r) if r else None}


@app.put("/api/marks/{kind}/{iid}")
async def mark_put(kind: str, iid: int, request: Request):
    try:
        body = await request.json()
        sev, ver = int(body.get("severity", 0)), int(body.get("verified", 0))
        cat, note = str(body.get("category") or ""), str(body.get("note") or "")[:5000]
    except Exception:
        raise HTTPException(400, "Ungültige Anfrage")
    if sev not in range(0, 6) or ver not in range(0, 3) or (cat and cat not in BY_KEY):
        raise HTTPException(400, "Ungültige Werte")
    return {"mark": upsert_mark(kind, iid, sev, cat, note, ver)}


def upsert_mark(kind: str, iid: int, sev: int, cat: str, note: str, ver: int):
    """Markierung setzen oder (sev=0) entfernen. Wird vom HTTP-Endpunkt und vom MCP-Server benutzt."""
    conn = db.connect()
    it = _mark_item(conn, kind, iid)
    if sev == 0:                                  # Stufe 0 entfernt die Markierung
        conn.execute("DELETE FROM marks WHERE kind = ? AND src = ? AND key = ?", (kind, it["src"], it["key"]))
        conn.commit()
        return None
    now = int(time.time())
    conn.execute(
        "INSERT INTO marks (kind, src, key, title, subtitle, severity, category, note, verified, created_ts, updated_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (kind, src, key) DO UPDATE SET title = excluded.title, "
        "subtitle = excluded.subtitle, severity = excluded.severity, category = excluded.category, "
        "note = excluded.note, verified = excluded.verified, updated_ts = excluded.updated_ts",
        (kind, it["src"], it["key"], it["title"], it["subtitle"], sev, cat, note, ver, now, now))
    conn.commit()
    r = conn.execute("SELECT * FROM marks WHERE kind = ? AND src = ? AND key = ?", (kind, it["src"], it["key"])).fetchone()
    return _mark_row(r)


# ---------- Trash ausblenden ----------

def mail_hide_clause(hide: str):
    """Bedingung, die die gewählten Trash-Gruppen ausblendet. Bewertete (markierte) Mails bleiben immer sichtbar."""
    keys = [k for k in (hide or "").split(",") if k in MAIL_KEYS]
    if not keys:
        return None, []
    ph = ",".join("?" * len(keys))
    return (f"(NOT EXISTS (SELECT 1 FROM msg_junk jk WHERE jk.id = m.id AND jk.grp IN ({ph})) "
            "OR EXISTS (SELECT 1 FROM marks mk2 WHERE mk2.kind = 'mail' "
            "AND mk2.src = m.source_path AND mk2.key = COALESCE(m.mbox_key, '')))"), keys


def doc_hide_clause(hide: str):
    conds = [DOC_COND[k] for k in (hide or "").split(",") if k in DOC_COND]
    if not conds:
        return None
    return ("(NOT COALESCE((" + " OR ".join(conds) + "), 0) OR EXISTS (SELECT 1 FROM marks mk2 "
            "WHERE mk2.kind = 'doc' AND mk2.src = d.path AND mk2.key = ''))")


@app.get("/api/junk/groups")
def junk_groups():
    conn = db.connect()
    counts = {r[0]: r[1] for r in conn.execute("SELECT grp, COUNT(*) FROM msg_junk GROUP BY grp")}
    return {
        "mail": [{"key": k, "label": lab, "desc": desc, "default": dflt, "count": counts.get(k, 0)}
                 for k, lab, desc, dflt, _c in MAIL_GROUPS],
        "docs": [{"key": k, "label": lab, "desc": desc, "default": dflt,
                  "count": conn.execute(f"SELECT COUNT(*) FROM documents d WHERE COALESCE(({cond}), 0)").fetchone()[0]}
                 for k, lab, desc, dflt, cond in DOC_GROUPS],
    }


# ---------- Adressen ----------

@app.get("/api/people/domains")
def people_domains():
    conn = db.connect()
    """Zähler für die Facetten: Stufen 1/2 (Einzeladressen) und Arten externer Domains."""
    levels = conn.execute("SELECT level, COUNT(DISTINCT CASE WHEN level = 1 THEN lower(COALESCE(name, addr)) "
                          "ELSE addr END) AS n FROM people GROUP BY level").fetchall()      # Stufe 1: Personen
    kinds = conn.execute("SELECT kind, COUNT(*) AS d, SUM(n_addrs) AS a, SUM(n_sent + n_recv) AS n "
                         "FROM domain_stats GROUP BY kind ORDER BY n DESC").fetchall()
    return {"levels": [{"level": r["level"], "count": r["n"]} for r in levels],
            "kinds": [{"kind": r["kind"], "domains": r["d"], "addrs": r["a"], "count": r["n"]} for r in kinds]}


@app.get("/api/people/detail")
def person(addr: str):
    a = addr.strip().lower()
    conn = db.connect()
    if a.startswith("@"):                       # Domain-Zeile (keine Einzeladressen)
        d = conn.execute("SELECT * FROM domain_stats WHERE domain = ?", (a[1:],)).fetchone()
        if not d:
            raise HTTPException(404)
        return {"addr": a, "name": a[1:], "level": 3, "source": d["kind"], "n_sent": d["n_sent"],
                "n_recv": d["n_recv"], "n_addrs": d["n_addrs"], "first_ts": None, "last_ts": None,
                "to_partners": [], "from_partners": [], "years": []}
    p = conn.execute("SELECT * FROM people WHERE addr = ?", (a,)).fetchone()
    if not p:
        raise HTTPException(404)
    to_p = from_p = years = []                  # Partner und Jahresverlauf nur für Stufe 1
    if p["level"] == 1:
        to_p = conn.execute("SELECT dst AS addr, n FROM pairs WHERE src = ? ORDER BY n DESC LIMIT 25", (a,)).fetchall()
        from_p = conn.execute("SELECT src AS addr, n FROM pairs WHERE dst = ? ORDER BY n DESC LIMIT 25", (a,)).fetchall()
        years = conn.execute("SELECT strftime('%Y', date_ts, 'unixepoch') AS year, COUNT(*) AS n FROM messages "
                             "WHERE lower(from_addr) = ? AND date_ts IS NOT NULL GROUP BY year ORDER BY year",
                             (a,)).fetchall()
    return {**dict(p), "to_partners": [dict(r) for r in to_p], "from_partners": [dict(r) for r in from_p],
            "years": [dict(r) for r in years]}


@app.get("/api/people")
def people(q: str = "", domain: str = Query("", alias="folder"), sort: str = "rank",
           offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    if domain.startswith("kind:"):              # externe Domains: nur Zähler je Domain
        kw, kargs = ["kind = ?"], [domain[5:]]
        for t in (q or "").split():
            kw.append("domain LIKE ? ESCAPE '\\'")
            kargs.append("%" + like_prefix(t))
        kconn = db.connect()
        ksql = "WHERE " + " AND ".join(kw)
        total = kconn.execute(f"SELECT COUNT(*) FROM domain_stats {ksql}", kargs).fetchone()[0]
        rows = kconn.execute(f"SELECT * FROM domain_stats {ksql} ORDER BY (n_sent + n_recv) DESC LIMIT ? OFFSET ?",
                             kargs + [limit, offset]).fetchall()
        return {"total": total, "items": [
            {"id": "@" + r["domain"], "addr": "@" + r["domain"], "name": r["domain"], "level": 3, "source": r["kind"],
             "n_addrs": r["n_addrs"], "n_sent": r["n_sent"], "n_recv": r["n_recv"], "last_ts": None} for r in rows]}

    where, args = [], []
    for t in (q or "").split():
        where.append("(addr LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
        args += ["%" + like_prefix(t)] * 2
    level = 2 if domain == "level:2" else 1     # Standard: Stufe 1; "level:2" = Parteidomain ohne Zuordnung
    where.append("level = ?")
    args.append(level)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    conn = db.connect()
    if level == 2:                              # Stufe 2: eine Zeile je Adresse
        order = {"date_desc": "last_ts DESC", "date_asc": "last_ts ASC"}.get(sort, "(n_sent + n_recv) DESC")
        total = conn.execute(f"SELECT COUNT(*) FROM people {wsql}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM people {wsql} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        return {"total": total, "items": [{**dict(r), "id": r["addr"], "n_addrs": 1} for r in rows]}
    # Stufe 1: eine Zeile je Person (alle Adressen mit gleichem Namen zusammengefasst)
    pkey = "lower(COALESCE(name, addr))"
    order = {"date_desc": "MAX(last_ts) DESC", "date_asc": "MAX(last_ts) ASC"}.get(sort, "SUM(n_sent + n_recv) DESC")
    total = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM people {wsql} GROUP BY {pkey})", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT {pkey} AS pkey, MIN(COALESCE(name, addr)) AS name, COUNT(*) AS n_addrs, SUM(n_sent) AS n_sent, "
        f"SUM(n_recv) AS n_recv, MIN(first_ts) AS first_ts, MAX(last_ts) AS last_ts, MIN(source) AS source "
        f"FROM people {wsql} GROUP BY {pkey} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    items = []
    for r in rows:
        top = conn.execute("SELECT addr FROM people WHERE level = 1 AND lower(COALESCE(name, addr)) = ? "
                           "ORDER BY n_sent + n_recv DESC LIMIT 1", (r["pkey"],)).fetchone()
        items.append({**dict(r), "id": "person:" + r["pkey"], "key": r["pkey"], "level": 1,
                      "addr": top["addr"] if top else ""})
    return {"total": total, "items": items}


@app.get("/api/people/person")
def person_group(key: str):
    """Eine Person mit allen ihren Adressen: Summen, Partner und Jahresverlauf über alle Adressen."""
    k = key.strip().lower()
    conn = db.connect()
    rows = conn.execute("SELECT * FROM people WHERE level = 1 AND lower(COALESCE(name, addr)) = ? "
                        "ORDER BY n_sent + n_recv DESC", (k,)).fetchall()
    if not rows:
        raise HTTPException(404)
    addrs = [r["addr"] for r in rows]
    ph = ",".join("?" * len(addrs))
    to_p = conn.execute(f"SELECT dst AS addr, SUM(n) AS n FROM pairs WHERE src IN ({ph}) AND dst NOT IN ({ph}) "
                        "GROUP BY dst ORDER BY n DESC LIMIT 25", addrs + addrs).fetchall()
    from_p = conn.execute(f"SELECT src AS addr, SUM(n) AS n FROM pairs WHERE dst IN ({ph}) AND src NOT IN ({ph}) "
                          "GROUP BY src ORDER BY n DESC LIMIT 25", addrs + addrs).fetchall()
    years = conn.execute(f"SELECT strftime('%Y', date_ts, 'unixepoch') AS year, COUNT(*) AS n FROM messages "
                         f"WHERE lower(from_addr) IN ({ph}) AND date_ts BETWEEN 631152000 AND 2051222400 "
                         "GROUP BY year ORDER BY year", addrs).fetchall()
    firsts = [r["first_ts"] for r in rows if r["first_ts"]]
    lasts = [r["last_ts"] for r in rows if r["last_ts"]]
    return {"key": k, "name": rows[0]["name"] or rows[0]["addr"], "level": 1,
            "sources": sorted({r["source"] for r in rows if r["source"]}),
            "addresses": [{"addr": r["addr"], "n_sent": r["n_sent"], "n_recv": r["n_recv"],
                           "first_ts": r["first_ts"], "last_ts": r["last_ts"]} for r in rows],
            "n_sent": sum(r["n_sent"] for r in rows), "n_recv": sum(r["n_recv"] for r in rows),
            "first_ts": min(firsts) if firsts else None, "last_ts": max(lasts) if lasts else None,
            "to_partners": [dict(r) for r in to_p], "from_partners": [dict(r) for r in from_p],
            "years": [dict(r) for r in years]}


# ---------- Dokumente ----------

DOC_OPS = {"name": "name", "datei": "name", "ext": "ext", "typ": "ext",
           "art": "genre", "genre": "genre",
           "vor": "before", "before": "before", "nach": "after", "after": "after",
           "quelle": "source", "source": "source"}


def parse_doc_query(q: str):
    fts, where, args = [], [], []
    for m in QTOKEN.finditer(q or ""):
        key = (m.group(1) or "").lower()
        val = m.group(2) if m.group(2) is not None else m.group(3)
        if key and key not in DOC_OPS:
            key, val = "", m.group(0).strip('"')
        val = (val or "").strip()
        if not val:
            continue
        op = DOC_OPS.get(key, "")
        if op == "name":
            fts.append(f"name : {fq(val)}")
        elif op == "ext":
            where.append("d.ext = ?")
            args.append(val.lower().lstrip("."))
        elif op == "genre":
            where.append("d.genre = ?")
            args.append(val.upper())
        elif op in ("before", "after"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
                where.append("d.doc_date < ?" if op == "before" else "d.doc_date >= ?")
                args.append(val)
        elif op == "source":
            where.append("d.source_set LIKE ? ESCAPE '\\'")
            args.append(like_prefix(val))
        else:
            fts.append(fq(val))
    return fts, where, args


def doc_title(head: str) -> str:
    """Erste sinnvolle Textzeile als Titel (Dateinamen sind Hashes)."""
    for line in (head or "").splitlines():
        line = line.strip(" \t -_=*|.:")
        if len(re.findall(r"\w", line)) >= 4:
            return line[:100]
    return ""


@app.get("/api/docs/types")
def doc_types():
    conn = db.connect()
    rows = conn.execute("SELECT ext, COUNT(*) AS n FROM documents GROUP BY ext ORDER BY n DESC").fetchall()
    return [{"ext": r["ext"], "count": r["n"]} for r in rows]


@app.get("/api/docs/genres")
def doc_genres():
    conn = db.connect()
    rows = conn.execute("SELECT genre, COUNT(*) AS n FROM documents WHERE genre IS NOT NULL "
                        "GROUP BY genre ORDER BY n DESC").fetchall()
    return [{"genre": r["genre"], "count": r["n"]} for r in rows]


@app.get("/api/docs")
def docs(q: str = "", ext: str = Query("", alias="folder"), sort: str = "rank", cat: str = "", hide: str = "",
         offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    fts, where, args = parse_doc_query(q)
    cc = cat_clause(cat)
    if cc:
        fts.append(cc)
    hc = doc_hide_clause(hide)
    if hc:
        where.append(hc)
    if ext.startswith("genre:"):
        where.append("d.genre = ?")
        args.append(ext[6:])
    elif ext.startswith("ext:"):
        where.append("d.ext = ?")
        args.append(ext[4:])
    elif ext:
        where.append("d.ext = ?")
        args.append(ext)

    cols = ("d.id, d.name, d.ext, d.size, d.path, d.preview, d.ocr_status, d.genre, d.doc_date, "
            "(SELECT severity FROM marks mk WHERE mk.kind = 'doc' AND mk.src = d.path AND mk.key = '') AS sev, "
            "substr(d.text, 1, 400) AS head")
    if fts:
        cols += ", snippet(documents_fts, 1, char(1), char(2), '…', 14) AS snip"
        frm = "FROM documents_fts JOIN documents d ON d.id = documents_fts.rowid"
        where.insert(0, "documents_fts MATCH ?")
        args.insert(0, " AND ".join(fts))
    else:
        cols += ", NULL AS snip"
        frm = "FROM documents d"
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    order = {"date_desc": "d.doc_date DESC", "date_asc": "(d.doc_date IS NULL), d.doc_date ASC",
             "rank": "rank" if fts else "d.name ASC"}.get(sort, "d.name ASC")

    conn = db.connect()
    try:
        total = conn.execute(f"SELECT COUNT(*) {frm} {wsql}", args).fetchone()[0]
        rows = conn.execute(f"SELECT {cols} {frm} {wsql} ORDER BY {order} LIMIT ? OFFSET ?",
                            args + [limit, offset]).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(400, f"Ungültige Suche: {e}")
    items = []
    for r in rows:
        d = dict(r)
        d["dir"] = os.path.dirname(d.pop("path"))
        d["title"] = doc_title(d.pop("head"))
        items.append(d)
    return {"total": total, "items": items}


@app.get("/api/docs/{did}")
def doc(did: int):
    conn = db.connect()
    r = conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
    if not r:
        raise HTTPException(404)
    return {"id": r["id"], "name": r["name"], "ext": r["ext"], "size": r["size"], "pages": r["pages"],
            "mtime": r["mtime"], "ocr_status": r["ocr_status"], "dir": os.path.dirname(r["path"]),
            "title": doc_title(r["text"]), "genre": r["genre"], "doc_date": r["doc_date"],
            "source_set": r["source_set"], "words": r["words"],
            "text": (r["text"] or "")[:300_000]}


@app.get("/api/docs/{did}/file")
def doc_file(did: int, inline: int = 0):
    conn = db.connect()
    r = conn.execute("SELECT path, name, ext FROM documents WHERE id = ?", (did,)).fetchone()
    if not r:
        raise HTTPException(404)
    root = os.path.realpath(raw_root())
    full = os.path.realpath(os.path.join(root, r["path"]))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, "Datei nicht lesbar")
    if inline and r["ext"] == "pdf":
        return FileResponse(full, media_type="application/pdf", filename=r["name"],
                            content_disposition_type="inline")
    return FileResponse(full, media_type="application/octet-stream", filename=r["name"],
                        content_disposition_type="attachment",
                        headers={"Content-Security-Policy": "sandbox"})


# ---------- Einrichtung, Jobs, Ordnerauswahl ----------

def _nearest_existing(p: Path) -> Path:
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def mcp_config() -> dict:
    """Eintrag für die Konfiguration eines KI-Clients (z. B. Claude Desktop) mit dem echten Programmpfad."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        cli = exe.with_name("hexane-desk" + exe.suffix)          # das Konsolenprogramm; das Fensterprogramm hat kein stdio
        cmd = str(cli if cli.exists() else exe)
    else:
        cmd = shutil.which("hexane-desk") or "hexane-desk"
    return {"mcpServers": {"hexane": {"command": cmd, "args": ["mcp"]}}}


@app.get("/api/setup/status")
def setup_status(refresh: int = 0):
    s = config.settings()
    root = config.data_root()
    idx = config.index_path()
    try:
        free = shutil.disk_usage(_nearest_existing(idx.parent)).free
    except OSError:
        free = None
    try:
        c = db.connect()
        counts = {"mails": c.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                  "docs": c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]}
        c.close()
    except Exception:
        counts = {"mails": 0, "docs": 0}
    return {
        "counts": counts,
        "version": __version__, "configured": bool(root and root.is_dir()), "data_dir": s.data_dir,
        "index_path": str(idx), "index_bytes": idx.stat().st_size if idx.exists() else 0, "free_bytes": free,
        "settings": {"mask_external": s.mask_external, "allow_write": s.allow_write, "lists_consent": s.lists_consent, "dns_consent": s.dns_consent},
        "detect": datasets.detect(root, fresh=bool(refresh)) if root else None,
        "overview": jobs.overview(), "lists_dir": str(config.lists_dir()), "lan": STATE["lan"],
        "mcp_config": mcp_config(),
    }


@app.post("/api/setup/config")
async def setup_config(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON erwartet")
    changes = {}
    if "data_dir" in body:
        d = str(body["data_dir"] or "").strip()
        if d and not Path(d).is_dir():
            raise HTTPException(400, "Dieser Ordner existiert nicht.")
        changes["data_dir"] = str(Path(d).resolve()) if d else ""
    if "index_dir" in body:
        changes["index_dir"] = str(body["index_dir"] or "").strip()
    for k in ("lists_consent", "mask_external", "allow_write", "dns_consent"):
        if k in body:
            changes[k] = bool(body[k])
    if jobs.running() and ("data_dir" in changes or "index_dir" in changes):
        raise HTTPException(409, "Während ein Schritt läuft, lässt sich der Ordner nicht ändern.")
    config.save(**changes)
    datasets.invalidate()
    if "data_dir" in changes or "index_dir" in changes:
        db.init()
    return setup_status(refresh=1)


@app.get("/api/jobs")
def jobs_overview():
    return jobs.overview()


@app.post("/api/jobs/start")
async def jobs_start(request: Request):
    body = await request.json()
    step = str(body.get("step", ""))
    if not config.data_root():
        raise HTTPException(409, "Es ist noch kein Datenordner gewählt.")
    try:
        if step == "all":
            jobs.start_sequence(jobs.RECOMMENDED)
        else:
            if step not in jobs.STEPS:
                raise HTTPException(400, "Unbekannter Schritt")
            ov = {x["key"]: x for x in jobs.overview()["steps"]}[step]
            if not ov["available"]:
                raise HTTPException(409, f"Schritt nicht verfügbar: {ov['reason']}")
            jobs.start(step)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.overview()


@app.post("/api/jobs/cancel")
def jobs_cancel():
    return {"cancelled": jobs.cancel()}


def _fs_roots() -> list[dict]:
    """Schnellzugriff der Ordnerauswahl: Laufwerke (Windows), eingebundene Datenträger (Linux/macOS), Home."""
    roots = [{"label": "Home", "path": str(Path.home())}]
    if os.name == "nt":
        import string
        roots += [{"label": f"{c}:\\", "path": f"{c}:\\"} for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
        return roots
    user = os.environ.get("USER") or Path.home().name
    for base in (f"/run/media/{user}", f"/media/{user}", "/media", "/mnt", "/Volumes"):
        try:
            for e in sorted(os.scandir(base), key=lambda e: e.name.lower()):
                if e.is_dir() and not e.name.startswith(".") and os.path.ismount(e.path):
                    roots.append({"label": e.name, "path": e.path})
        except OSError:
            continue
    return roots


@app.get("/api/fs/list")
def fs_list(path: str = ""):
    """Ordnerauswahl im Browser-Modus (im Desktop-Fenster gibt es den Dialog des Systems). Nur bei lokalem Betrieb."""
    if STATE["lan"]:
        raise HTTPException(403, "Die Ordnerauswahl ist im Netzwerk-Modus abgeschaltet.")
    roots = _fs_roots()
    if not path:
        path = str(Path.home())
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(404, "Ordner nicht gefunden")
    entries = []
    try:
        for e in sorted(os.scandir(p), key=lambda e: e.name.lower()):
            if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                entries.append({"name": e.name, "path": e.path})
    except OSError:
        raise HTTPException(403, "Keine Berechtigung für diesen Ordner")
    names = {e["name"] for e in entries}
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "entries": entries[:1000],
            "roots": roots, "looks_like_data": bool(names & set(datasets.PARTS)) or any(n in names for n in ("01_EMAIL", "03_DOCUMENTS"))}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
