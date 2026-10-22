"""Echtheits-Statistik: wie viele Mails je Postfach tragen eine DKIM-Signatur, deren Hash zum Text passt?

    (Schritt „Echtheits-Statistik“ der Einrichtung)

Liest die Mails erneut aus den mbox-Dateien (nur lesend) und speichert je Mail nur Zähler und Prüfergebnisse, keinen Text:
Anzahl Signaturen, Anzahl passender Hashes und die Ergebnisse (pass/fail/…) aus der Authentication-Results-Zeile des Empfangsservers.
Das ist KEINE Schlüsselprüfung (die braucht das Internet, siehe Echtheitsbericht), sondern zeigt, auf wie vielen Mails
eine spätere Prüfung überhaupt möglich ist und wo es Auffälligkeiten gibt. Kann unterbrochen und fortgesetzt werden.
"""
import os
import re
from collections import defaultdict

from . import authenticity as au
from . import config, db

MAX_BYTES = 40 * 1024 * 1024
COMMIT_EVERY = 2000


def analyze_raw(data: bytes) -> tuple:
    """(Anzahl Signaturen, Anzahl passender Hashes, dkim, spf, dmarc) aus den Rohbytes einer Mail."""
    head, body = au.split(data)
    headers = au.unfold(head)
    sigs = [au.tags(v) for n, v in headers if n.lower() == "dkim-signature"]
    match = sum(1 for s in sigs if au.body_hash_check(s, body) == "match") if sigs else 0
    res = {"dkim": "", "spf": "", "dmarc": ""}
    for n, v in headers:
        if n.lower() == "authentication-results":
            for k, r in re.findall(r"\b(spf|dkim|dmarc)\s*=\s*(\w+)", v, re.I):
                if not res[k.lower()]:                      # die erste (oberste) Zeile zählt
                    res[k.lower()] = r.lower()
    return len(sigs), match, res["dkim"], res["spf"], res["dmarc"]


def main(ctx=None, base: str | None = None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    db.init()
    base = base or str(config.data_root())
    conn = db.connect()
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    todo = conn.execute("SELECT COUNT(*) FROM messages m LEFT JOIN auth_stats a ON a.msg_id = m.id WHERE a.msg_id IS NULL").fetchone()[0]
    ctx.log(f"{todo} von {total} Mails noch zu prüfen")
    ctx.update(done=total - todo, total=total, message="Echtheits-Statistik")
    files = [r[0] for r in conn.execute(
        "SELECT DISTINCT m.source_path FROM messages m LEFT JOIN auth_stats a ON a.msg_id = m.id WHERE a.msg_id IS NULL ORDER BY 1")]
    done = total - todo
    for path in files:
        ctx.check()
        full = os.path.normpath(os.path.join(os.path.abspath(base), path))
        if not full.startswith(os.path.abspath(base) + os.sep) or not os.path.isfile(full):
            continue
        rows = conn.execute(
            "SELECT m.id, m.mbox_key FROM messages m LEFT JOIN auth_stats a ON a.msg_id = m.id "
            "WHERE a.msg_id IS NULL AND m.source_path = ? AND m.mbox_key IS NOT NULL", (path,)).fetchall()
        rows.sort(key=lambda r: int(str(r["mbox_key"]).split(":")[0]))          # in Dateireihenfolge lesen
        out = []
        with open(full, "rb") as f:
            for r in rows:
                off, ln = (int(x) for x in str(r["mbox_key"]).split(":"))
                if ln > MAX_BYTES:
                    out.append((r["id"], 0, 0, "", "", "", 1))
                    continue
                f.seek(off)
                data = f.read(ln)
                data = data.split(b"\n", 1)[1] if b"\n" in data else b""
                try:
                    out.append((r["id"], *analyze_raw(data), 0))
                except Exception:
                    out.append((r["id"], 0, 0, "", "", "", 1))
                if len(out) >= COMMIT_EVERY:
                    conn.executemany("INSERT OR REPLACE INTO auth_stats (msg_id, sigs, bh_ok, ar_dkim, ar_spf, ar_dmarc, skipped) VALUES (?,?,?,?,?,?,?)", out)
                    conn.commit()
                    done += len(out)
                    out = []
                    ctx.update(done=done, total=total)
                    ctx.check()
        if out:
            conn.executemany("INSERT OR REPLACE INTO auth_stats (msg_id, sigs, bh_ok, ar_dkim, ar_spf, ar_dmarc, skipped) VALUES (?,?,?,?,?,?,?)", out)
            conn.commit()
            done += len(out)
            ctx.update(done=done, total=total)
    ctx.log(f"Fertig: {done} Mails geprüft")
    conn.close()


def summary(conn) -> dict:
    """Auswertung je Postfach (Ordner) für die Anzeige."""
    rows = conn.execute(
        "SELECT m.folder AS folder, COUNT(*) AS n, SUM(a.sigs > 0) AS signed, SUM(a.bh_ok > 0) AS hash_ok, "
        "SUM(a.ar_dkim = 'pass') AS ar_pass, SUM(a.ar_dkim IN ('fail','permerror')) AS ar_fail "
        "FROM auth_stats a JOIN messages m ON m.id = a.msg_id GROUP BY m.folder ORDER BY n DESC").fetchall()
    out = [{k: (r[k] or 0) if k != "folder" else r[k] for k in r.keys()} for r in rows]
    tot = defaultdict(int)
    for r in out:
        for k in ("n", "signed", "hash_ok", "ar_pass", "ar_fail"):
            tot[k] += r[k]
    return {"folders": out, "total": dict(tot)}
