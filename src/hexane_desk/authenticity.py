"""Echtheits-Indizien für einzelne Mails (Schritt „Echtheits-Statistik“ und Echtheitsbericht).

Alles hier liefert Hinweise, keine Beweise. Stärkster Beleg ist eine gültige DKIM-Signatur (nur mit Internet: der öffentliche
Schlüssel kommt aus dem DNS und existiert bei alten Mails oft nicht mehr). Offline lässt sich prüfen, ob der Text zum Hash
in der Signatur passt, ob Zeitstempel und Zustellweg stimmig sind und ob Verweise und Anhänge zusammenpassen.
"""
import base64
import email
import hashlib
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

OK, WARN, BAD, INFO, NA = "ok", "warn", "bad", "info", "na"
MAX_ATT = 20
MAX_ATT_BYTES = 30 * 1024 * 1024


# ---------- Zerlegen ----------

def split(data: bytes) -> tuple[bytes, bytes]:
    m = re.search(rb"\r?\n\r?\n", data)
    return (data[:m.start()], data[m.end():]) if m else (data, b"")


def unfold(head: bytes) -> list[tuple[str, str]]:
    """Header als (Name, Wert) mit aufgelösten Umbrüchen, in Dateireihenfolge."""
    out, cur = [], None
    for line in re.split(rb"\r?\n", head):
        if line[:1] in (b" ", b"\t") and cur:
            cur[1] += b" " + line.strip()
        elif b":" in line:
            if cur:
                out.append(cur)
            n, _, v = line.partition(b":")
            cur = [n.strip(), v.strip()]
    if cur:
        out.append(cur)
    return [(n.decode("latin-1"), " ".join(v.decode("utf-8", "replace").split())) for n, v in out]


def tags(value: str) -> dict:
    d = {}
    for part in value.split(";"):
        k, _, v = part.partition("=")
        if k.strip():
            d[k.strip().lower()] = "".join(v.split())
    return d


# ---------- DKIM, offline: passt der Text zum Hash der Signatur? ----------

def _canon_body(body: bytes, relaxed: bool) -> bytes:
    lines = body.replace(b"\r\n", b"\n").split(b"\n")
    if relaxed:
        lines = [re.sub(rb"[ \t]+", b" ", l).rstrip(b" ") for l in lines]
    while lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        return b"" if relaxed else b"\r\n"
    return b"\r\n".join(lines) + b"\r\n"


def _unquote_mbox(body: bytes) -> bytes:
    """mboxrd: beim Export wurde vor „From “-Zeilen im Text ein „>“ gesetzt."""
    return re.sub(rb"(?m)^>(>*From )", rb"\1", body)


def body_hash_check(sig: dict, body: bytes) -> str:
    """'match' | 'mismatch' | 'unsupported'"""
    algo = sig.get("a", "")
    h = {"rsa-sha256": hashlib.sha256, "ed25519-sha256": hashlib.sha256, "rsa-sha1": hashlib.sha1}.get(algo)
    if not h or not sig.get("bh"):
        return "unsupported"
    relaxed = sig.get("c", "simple/simple").partition("/")[2] == "relaxed" if "/" in sig.get("c", "") else False
    limit = int(sig["l"]) if sig.get("l", "").isdigit() else None
    for b in (body, _unquote_mbox(body)):
        c = _canon_body(b, relaxed)
        if limit is not None:
            c = c[:limit]
        if base64.b64encode(h(c).digest()).decode() == sig["bh"]:
            return "match"
    return "mismatch"


def dkim_online(data: bytes, idx: int, dnsfunc=None) -> tuple[str, str]:
    """Signatur mit öffentlichem Schlüssel aus dem DNS prüfen: ('valid'|'invalid'|'nokey'|'unavailable', Detail)."""
    try:
        import dkim
    except ImportError:
        return "unavailable", "Das Paket dkimpy ist nicht installiert (pip install dkimpy)."
    import logging

    class _Collect(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, rec):
            self.lines.append(rec.getMessage())

    head, body = split(data)
    candidates = [data]
    if re.search(rb"(?m)^>+From ", body):                       # mboxrd-Maskierung rückgängig machen
        candidates.append(head + b"\n\n" + _unquote_mbox(body))
    detail = ""
    for cand in candidates:
        h = _Collect()
        logger = logging.Logger("hexane-dkim")
        logger.addHandler(h)
        try:
            kw = {"dnsfunc": dnsfunc} if dnsfunc else {}
            if dkim.DKIM(cand, logger=logger).verify(idx, **kw):
                return "valid", ""
        except Exception as e:                                  # kaputte Signatur, DNS-Fehler
            h.lines.append(str(e))
        detail = " ".join(h.lines)
    kind = "nokey" if re.search(r"missing public key|key not found|nxdomain|no (?:public )?key|dns (?:lookup|error|failure)|timed? ?out", detail, re.I) else "invalid"
    return kind, detail[-200:]


# ---------- Einzelprüfungen ----------

def _check(cid, level, title, detail=""):
    return {"id": cid, "level": level, "title": title, "detail": detail}


def _dt(value):
    try:
        d = parsedate_to_datetime(value)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def check_dkim(headers, body, data, online=False, dnsfunc=None) -> tuple[list, list]:
    sigs = [tags(v) for n, v in headers if n.lower() == "dkim-signature"]
    checks, rows = [], []
    if not sigs:
        return [_check("dkim", INFO, "Keine DKIM-Signatur", "Die Herkunft lässt sich nicht kryptografisch belegen. Das ist kein Hinweis auf eine Fälschung.")], rows
    for i, s in enumerate(sigs):
        row = {"domain": (s.get("d") or "").lower(), "selector": s.get("s", ""), "algo": s.get("a", ""),
               "body_hash": body_hash_check(s, body), "signature": None, "detail": ""}
        if online:
            row["signature"], row["detail"] = dkim_online(data, i, dnsfunc)
        rows.append(row)
        who = f"{row['domain']} (Selector {row['selector']})"
        if row["signature"] == "valid":
            checks.append(_check(f"dkim{i}", OK, f"DKIM-Signatur gültig: {who}",
                                 "Text und signierte Header wurden seit dem Versand nicht verändert; die Mail wurde von einem Server dieser Domain signiert."))
        elif row["signature"] == "invalid":
            checks.append(_check(f"dkim{i}", BAD if row["body_hash"] == "mismatch" else WARN, f"DKIM-Signatur ungültig: {who}",
                                 "Beim Export können Zeilenumbrüche oder Betreff-Zusätze (Listen) die Signatur gebrochen haben. " + row["detail"]))
        elif row["signature"] == "nokey":
            checks.append(_check(f"dkim{i}", NA, f"DKIM-Schlüssel nicht abrufbar: {who}",
                                 "Der öffentliche Schlüssel steht nicht mehr im DNS (oft nach Schlüsselwechsel). Die Signatur ist nicht prüfbar."))
        elif row["signature"] == "unavailable":
            checks.append(_check(f"dkim{i}", NA, f"DKIM-Signatur nicht prüfbar: {who}", row["detail"]))
        if row["signature"] in (None, "nokey", "unavailable"):
            if row["body_hash"] == "match":
                checks.append(_check(f"bh{i}", INFO, f"Text passt zum Hash in der Signatur ({row['domain']})",
                                     "Nur ein Hinweis auf Unverändertheit: Ohne Schlüsselprüfung kann ein Fälscher Signatur und Hash neu schreiben."))
            elif row["body_hash"] == "mismatch":
                checks.append(_check(f"bh{i}", WARN, f"Text passt NICHT zum Hash in der Signatur ({row['domain']})",
                                     "Der Text wurde nach dem Signieren verändert, oder der Export hat ihn verändert (Zeilenumbrüche, Kodierung)."))
    return checks, rows


def check_auth_results(headers) -> list:
    out = []
    for n, v in headers:
        if n.lower() != "authentication-results":
            continue
        server = v.split(";")[0].strip()
        res = {k.lower(): r.lower() for k, r in re.findall(r"\b(spf|dkim|dmarc)\s*=\s*(\w+)", v, re.I)}
        if not res:
            continue
        txt = ", ".join(f"{k}={r}" for k, r in sorted(res.items()))
        bad = [k for k, r in res.items() if r in ("fail", "softfail", "permerror")]
        lvl = BAD if "dmarc" in bad or "dkim" in bad else WARN if bad else OK if "pass" in res.values() else INFO
        out.append(_check("ar", lvl, f"Prüfergebnis des empfangenden Servers ({server}): {txt}",
                          "Diese Zeile hat der Empfangsserver beim Eingang eingetragen. Sie ist nur so vertrauenswürdig wie dieser Server; "
                          "eine Fälschung kann eigene Zeilen mitbringen."))
    return out


def check_received(headers, date_hdr) -> list:
    rec = [v for n, v in headers if n.lower() == "received"]
    if not rec:
        return [_check("rcv", WARN, "Keine Received-Zeilen", "Der Zustellweg lässt sich nicht nachvollziehen.")]
    times = []
    for v in rec:
        d = _dt(v.rsplit(";", 1)[1].strip()) if ";" in v else None
        times.append(d)
    out, known = [], [t for t in times if t]
    if len(known) >= 2:
        backwards = [(a, b) for a, b in zip(known, known[1:]) if b - a > timedelta(minutes=10)]   # [0] ist die neueste Zeile
        if backwards:
            out.append(_check("rcv_order", WARN, "Zeitstempel im Zustellweg nicht aufsteigend",
                              f"{len(backwards)} Sprünge rückwärts (mehr als 10 Minuten). Uhrabweichungen kommen vor, Fälschungen erzeugen sie auch."))
        else:
            out.append(_check("rcv_order", OK, f"Zustellweg stimmig ({len(rec)} Stationen)", "Die Zeitstempel steigen vom Absender zum Empfänger."))
    else:
        out.append(_check("rcv_order", INFO, f"Zustellweg mit {len(rec)} Station(en)", "Zu wenige Zeitstempel für einen Vergleich."))
    d = _dt(date_hdr) if date_hdr else None
    if d and known:
        diff = (known[0] - d).total_seconds()
        if diff < -3600:
            out.append(_check("rcv_date", WARN, "Mail ist angeblich nach dem Eingang geschrieben",
                              f"Das Datum der Mail liegt {abs(diff) / 3600:.1f} Stunden NACH dem obersten Received-Eintrag."))
        elif diff > 2 * 86400:
            out.append(_check("rcv_date", WARN, "Große Lücke zwischen Datum und Eingang", f"{diff / 86400:.0f} Tage zwischen Date und oberster Received-Zeile."))
        else:
            out.append(_check("rcv_date", OK, "Datum passt zum Eingang", "Date und oberste Received-Zeile liegen dicht beieinander."))
    return out


def check_from_line(from_line: str, date_hdr: str) -> list:
    m = re.match(r"From \S+\s+(.+)$", from_line or "")
    if not m or not date_hdr:
        return []
    try:
        f = datetime.strptime(" ".join(m.group(1).split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return []
    d = _dt(date_hdr)
    if not d:
        return []
    diff = abs((f - d).total_seconds()) / 86400
    if diff > 2:
        return [_check("fromline", INFO, f"mbox-Trennzeile weicht {diff:.0f} Tage vom Datum ab",
                       "Die Trennzeile stammt vom Export oder vom Mailserver und kann beliebig sein. Ein Hinweis, kein Befund.")]
    return [_check("fromline", OK, "mbox-Trennzeile passt zum Datum", "")]


def check_identity(headers) -> list:
    g = lambda name: next((v for n, v in headers if n.lower() == name), "")
    dom = lambda s: (re.search(r"@([A-Za-z0-9.-]+)", s) or [None, ""])[1].lower().rstrip(".")
    out = []
    f, rp, rt = dom(g("from")), dom(g("return-path")), dom(g("reply-to"))
    if f and rp and f != rp and not rp.endswith("." + f) and not f.endswith("." + rp):
        out.append(_check("envelope", INFO, f"Absender ({f}) und Return-Path ({rp}) weichen ab",
                          "Bei Newslettern, Diensten und Weiterleitungen üblich."))
    if f and rt and f != rt and not rt.endswith("." + f) and not f.endswith("." + rt):
        out.append(_check("replyto", INFO, f"Antwortadresse ({rt}) liegt auf anderer Domain als der Absender ({f})",
                          "Bei Phishing häufig, sonst auch bei Newslettern und Formularen."))
    mid = g("message-id")
    if not mid:
        out.append(_check("msgid", WARN, "Keine Message-ID", "Normale Mailserver und Programme vergeben immer eine."))
    elif not re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", mid.strip()):
        out.append(_check("msgid", WARN, "Message-ID hat ein ungewöhnliches Format", mid[:100]))
    return out


def check_thread(conn, headers, thread_id, own_id) -> list:
    if conn is None:
        return []
    g = lambda name: next((v for n, v in headers if n.lower() == name), "")
    out = []
    irt = re.findall(r"<[^<>\s]+>", g("in-reply-to"))
    if irt:
        hit = conn.execute("SELECT id FROM messages WHERE message_id = ? LIMIT 1", (irt[0],)).fetchone()
        out.append(_check("irt", OK if hit else INFO, "Mail, auf die geantwortet wird, ist im Datensatz" if hit else
                          "Mail, auf die geantwortet wird, fehlt im Datensatz",
                          "Antworten, die den Text der Vorlage zitieren, lassen sich damit vergleichen." if hit else
                          "Der Datensatz ist entdoppelt und enthält nicht jede Mail; das ist allein kein Befund."))
    if thread_id:
        n = conn.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ? AND id <> ?", (thread_id, own_id)).fetchone()[0]
        if n:
            out.append(_check("thread", OK, f"{n} weitere Mail(s) im selben Gesprächsverlauf", "Stimmige Verläufe sprechen gegen eine einzeln erfundene Mail."))
    mid = g("message-id")
    if mid:
        dup = conn.execute("SELECT COUNT(*) FROM messages WHERE message_id = ? AND id <> ?", (mid, own_id)).fetchone()[0]
        if dup:
            out.append(_check("dup", WARN, f"Message-ID kommt {dup}× weiteres Mal im Datensatz vor", "Der Datensatz wurde nach Message-ID entdoppelt; Doppelte sollten nicht vorkommen."))
    return out


# ---------- Anhänge ----------

def _pdf_meta(blob: bytes) -> dict:
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(blob))
        m = r.metadata or {}
        return {"created": _pdf_date(m.get("/CreationDate")), "modified": _pdf_date(m.get("/ModDate")),
                "program": str(m.get("/Producer") or m.get("/Creator") or "")[:80]}
    except Exception:
        return {}


def _pdf_date(v):
    m = re.match(r"D:(\d{4})(\d\d)(\d\d)(\d\d)?(\d\d)?(\d\d)?", str(v or ""))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x or 0) for x in m.groups())
    try:
        return datetime(y, mo or 1, d or 1, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None


def _office_meta(blob: bytes) -> dict:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        core = z.read("docProps/core.xml").decode("utf-8", "replace")
        app = z.read("docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in z.namelist() else ""
        pick = lambda tag, s: (re.search(rf"<{tag}[^>]*>([^<]+)<", s) or [None, ""])[1]
        iso = lambda s: _dt_iso(s)
        return {"created": iso(pick("dcterms:created", core)), "modified": iso(pick("dcterms:modified", core)),
                "program": pick("Application", app)[:80]}
    except Exception:
        return {}


def _dt_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def attachments(msg, mail_date) -> tuple[list, list]:
    rows, checks = [], []
    n = 0
    for part in msg.walk():
        if part.is_multipart() or not (part.get_filename() or part.get_content_disposition() == "attachment"):
            continue
        n += 1
        if n > MAX_ATT:
            break
        try:
            blob = part.get_payload(decode=True) or b""
        except Exception:
            continue
        row = {"name": part.get_filename() or "(ohne Namen)", "type": part.get_content_type(), "size": len(blob),
               "sha256": hashlib.sha256(blob).hexdigest()}
        if len(blob) <= MAX_ATT_BYTES:
            name = row["name"].lower()
            meta = _pdf_meta(blob) if blob[:5] == b"%PDF-" else _office_meta(blob) if name.endswith(("docx", "xlsx", "pptx")) else {}
            if meta:
                row.update({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in meta.items()})
                c = meta.get("created")
                if c and mail_date and c - mail_date > timedelta(days=1):
                    checks.append(_check(f"att{n}", WARN, f"Anhang „{row['name'][:60]}“ ist laut Metadaten NACH der Mail erstellt",
                                         f"Erstellt {c:%d.%m.%Y}, Mail {mail_date:%d.%m.%Y}. Metadaten lassen sich ändern; auch Nachbearbeitung im Export ist denkbar."))
        rows.append(row)
    if rows and not checks:
        checks.append(_check("att", INFO, f"{len(rows)} Anhang/Anhänge mit Prüfsumme", "Die Prüfsummen erlauben, dieselbe Datei an anderer Stelle wiederzufinden."))
    return rows, checks


# ---------- Gesamtbericht ----------

def analyze(data: bytes, from_line: str = "", conn=None, own_id=None, thread_id=None, online=False, dnsfunc=None,
            location: dict | None = None) -> dict:
    head, body = split(data)
    headers = unfold(head)
    g = lambda name: next((v for n, v in headers if n.lower() == name), "")
    date_hdr = g("date")
    mail_date = _dt(date_hdr)
    checks, dkim_rows = check_dkim(headers, body, data, online=online, dnsfunc=dnsfunc)
    checks += check_auth_results(headers) + check_received(headers, date_hdr) + check_from_line(from_line, date_hdr)
    checks += check_identity(headers) + check_thread(conn, headers, thread_id, own_id)
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
        att_rows, att_checks = attachments(msg, mail_date)
    except Exception:
        att_rows, att_checks = [], []
    checks += att_checks
    n = {lvl: sum(1 for c in checks if c["level"] == lvl) for lvl in (OK, WARN, BAD, INFO, NA)}
    verdict = BAD if n[BAD] else WARN if n[WARN] else OK if n[OK] else INFO
    label = {BAD: "Deutliche Auffälligkeiten", WARN: "Auffälligkeiten", OK: "Indizien sprechen für Echtheit",
             INFO: "Keine belastbaren Indizien in eine Richtung"}[verdict]
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "location": location or {}, "verdict": verdict,
            "verdict_text": label, "counts": n, "checks": checks, "dkim": dkim_rows, "attachments": att_rows,
            "note": "Ergebnisse sind Indizien, keine Beweise. Header lassen sich fälschen; Echtheit heißt nur, dass die Mail so verschickt wurde, "
                    "nicht, dass ihr Inhalt stimmt. Fehlende Signaturen beweisen nichts."}


def to_markdown(rep: dict, title: str = "") -> str:
    sym = {OK: "✔", WARN: "⚠", BAD: "✖", INFO: "•", NA: "?"}
    loc = rep.get("location") or {}
    lines = [f"# Echtheitsbericht{': ' + title if title else ''}", "", f"**Gesamteindruck:** {rep['verdict_text']}", "",
             f"- SHA-256 der Roh-Mail: `{rep['sha256']}` ({rep['size']} Bytes)"]
    if loc:
        lines.append(f"- Fundort: `{loc.get('file', '')}`, Offset/Länge `{loc.get('key', '')}`")
    lines += ["", "## Prüfungen"] + [f"- {sym[c['level']]} **{c['title']}**" + (f" – {c['detail']}" if c["detail"] else "") for c in rep["checks"]]
    if rep["attachments"]:
        lines += ["", "## Anhänge"] + [f"- {a['name']} ({a['size']} B) `{a['sha256']}`" for a in rep["attachments"]]
    lines += ["", f"_{rep['note']}_"]
    return "\n".join(lines) + "\n"
