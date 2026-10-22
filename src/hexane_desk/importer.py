"""Liest Mails (mbox, .eml, Maildir) aus einem Verzeichnis in den SQLite-Index.

Die Rohdateien werden nur gelesen, nie verändert und nie ausgeführt.
Mehrere Worker-Prozesse parsen parallel, der Hauptprozess schreibt in die Datenbank.
Fertig importierte Dateien werden in `import_done` vermerkt; ein erneuter Aufruf setzt dort fort.

    python -m app.importer /raw/01_EMAIL

Erwartetes Layout (hexane): 01_EMAIL/<postfach>/part-NN.mbox
"""
import email
import multiprocessing as mp
import queue as queue_mod
import os
import re
import sys
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape

from . import db

BATCH = 200
TEXT_LIMIT = 300_000          # Zeichen je Mail im Index
_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"(?is)<(script|style).*?</\1>")
_WS = re.compile(r"\s+")
_MSGID = re.compile(r"<[^>]+>")
# mbox-Trennzeile: "From absender Mon Jan  1 00:00:00 2024"
FROM_RE = re.compile(rb"^From \S+\s.*\d\d:\d\d")


def html_to_text(html: str) -> str:
    return _WS.sub(" ", unescape(_TAG.sub(" ", _STYLE.sub(" ", html)))).strip()


def addrs(value) -> list[tuple[str, str]]:
    return [(n, a) for n, a in getaddresses([str(value)] if value else []) if a]


def split_mbox(path: str):
    """Liefert (offset, länge, bytes ohne From_-Zeile) je Mail, speicherschonend."""
    off, start, buf = 0, None, []
    with open(path, "rb") as f:
        for line in f:
            if FROM_RE.match(line):
                if start is not None:
                    yield start, off - start, b"".join(buf)
                start, buf = off, []
            elif start is not None:
                buf.append(line)
            off += len(line)
    if start is not None:
        yield start, off - start, b"".join(buf)


def thread_key(msg: EmailMessage) -> str:
    """Wurzel-Message-ID des Verlaufs; ohne Referenzen bildet die Mail ihren eigenen Verlauf."""
    refs = _MSGID.findall(str(msg.get("References", "")))
    if refs:
        return refs[0]
    irt = _MSGID.findall(str(msg.get("In-Reply-To", "")))
    if irt:
        return irt[0]
    return (_MSGID.findall(str(msg.get("Message-ID", ""))) or [""])[0]


def att_size(part) -> int:
    p = part.get_payload()
    if not isinstance(p, str):
        return 0
    cte = str(part.get("Content-Transfer-Encoding", "")).lower()
    return len(p) * 3 // 4 if cte == "base64" else len(p)


def extract(msg: EmailMessage) -> dict:
    subject = str(msg.get("Subject", "") or "")
    frm = addrs(msg.get("From"))
    from_name, from_addr = frm[0] if frm else ("", "")
    to = ", ".join(a for _, a in addrs(msg.get("To")))
    cc = ", ".join(a for _, a in addrs(msg.get("Cc")))

    ts = None
    try:
        ts = int(parsedate_to_datetime(str(msg.get("Date"))).timestamp())
    except Exception:
        pass

    text, has_html = "", 0
    try:
        plain = msg.get_body(preferencelist=("plain",))
        html = msg.get_body(preferencelist=("html",))
        has_html = 1 if html is not None else 0
        if plain is not None:
            text = plain.get_content()
        elif html is not None:
            text = html_to_text(html.get_content())
    except Exception:
        text = ""
    text = text[:TEXT_LIMIT]

    atts = []
    for i, part in enumerate(msg.iter_attachments()):
        atts.append((i, part.get_filename() or "", part.get_content_type(), att_size(part)))

    return {
        "message_id": (_MSGID.findall(str(msg.get("Message-ID", ""))) or [""])[0],
        "thread_id": thread_key(msg),
        "from_name": from_name, "from_addr": from_addr,
        "to_addrs": to, "cc_addrs": cc,
        "subject": subject, "date_ts": ts,
        "preview": _WS.sub(" ", text)[:200],
        "body_text": text, "has_html": has_html,
        "atts": atts,
    }


def _dh(value) -> str:
    """Header dekodieren; bei kaputten Headern den Rohtext verwenden. Keine Zeilenumbrüche."""
    try:
        s = str(make_header(decode_header(str(value or ""))))
    except Exception:
        s = str(value or "")
    return s.replace("\r", " ").replace("\n", " ").strip()


def extract_lenient(data: bytes) -> dict:
    """Fallback für Mails mit kaputten Headern: nutzt den toleranten compat32-Parser."""
    msg = email.message_from_bytes(data)
    try:
        frm = addrs(_dh(msg.get("From")))
        to = ", ".join(a for _, a in addrs(_dh(msg.get("To"))))
        cc = ", ".join(a for _, a in addrs(_dh(msg.get("Cc"))))
    except Exception:
        frm, to, cc = [], _dh(msg.get("To")), _dh(msg.get("Cc"))
    from_name, from_addr = frm[0] if frm else (_dh(msg.get("From")), "")

    ts = None
    try:
        ts = int(parsedate_to_datetime(str(msg.get("Date"))).timestamp())
    except Exception:
        pass

    text, html_text, atts = "", "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        try:
            fname = _dh(part.get_filename())
        except Exception:
            fname = ""
        if fname or "attachment" in str(part.get("Content-Disposition", "")).lower():
            atts.append((len(atts), fname, ctype, len(part.get_payload() or "") * 3 // 4))
            continue
        if ctype not in ("text/plain", "text/html"):
            continue
        raw = part.get_payload(decode=True) or b""
        try:
            s = raw.decode(part.get_content_charset() or "utf-8", "replace")
        except LookupError:
            s = raw.decode("utf-8", "replace")
        if ctype == "text/plain" and not text:
            text = s
        elif ctype == "text/html" and not html_text:
            html_text = s
    if not text and html_text:
        text = html_to_text(html_text)
    text = text[:TEXT_LIMIT]

    return {
        "message_id": (_MSGID.findall(str(msg.get("Message-ID", ""))) or [""])[0],
        "thread_id": thread_key(msg),
        "from_name": from_name, "from_addr": from_addr,
        "to_addrs": to, "cc_addrs": cc,
        "subject": _dh(msg.get("Subject")), "date_ts": ts,
        "preview": _WS.sub(" ", text)[:200],
        "body_text": text, "has_html": 1 if html_text else 0,
        "atts": atts,
    }


def parse_any(parser, data: bytes) -> dict:
    try:
        return extract(parser.parsebytes(data))
    except Exception:
        return extract_lenient(data)


def store(conn, folder: str, source_path: str, mbox_key, size: int, m: dict) -> None:
    cur = conn.execute(
        """INSERT OR IGNORE INTO messages
           (folder, source_path, mbox_key, message_id, thread_id, from_name, from_addr,
            to_addrs, cc_addrs, subject, date_ts, preview, body_text, has_html, att_count, size)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (folder, source_path, mbox_key, m["message_id"], m["thread_id"], m["from_name"],
         m["from_addr"], m["to_addrs"], m["cc_addrs"], m["subject"], m["date_ts"],
         m["preview"], m["body_text"], m["has_html"], len(m["atts"]), size),
    )
    if cur.rowcount == 0:
        return
    mid = cur.lastrowid
    conn.execute(
        "INSERT INTO messages_fts (rowid, subject, from_text, to_text, body) VALUES (?,?,?,?,?)",
        (mid, m["subject"], f'{m["from_name"]} {m["from_addr"]}',
         f'{m["to_addrs"]} {m["cc_addrs"]}', m["body_text"]),
    )
    for i, name, ctype, asize in m["atts"]:
        conn.execute(
            "INSERT INTO attachments (message_id, part_index, filename, content_type, size) "
            "VALUES (?,?,?,?,?)", (mid, i, name, ctype, asize))


def folder_of(root: str, path: str) -> str:
    rel = os.path.relpath(os.path.dirname(path), root)
    parts = [p for p in rel.split(os.sep) if p not in (".", "cur", "new", "tmp")]
    while parts and parts[0] == os.path.basename(root):    # 01_EMAIL/01_EMAIL/<postfach>
        parts.pop(0)
    return "/".join(parts) or os.path.basename(root)


def kind_of(path: str):
    low = os.path.basename(path).lower()
    if low.endswith(".mbox") or low == "mbox":
        return "mbox"
    if low.endswith(".eml") or os.path.basename(os.path.dirname(path)) in ("cur", "new"):
        return "eml"
    return None


def iter_records(base: str, path: str, folder: str, kind: str):
    rel = os.path.relpath(path, base)
    parser = BytesParser(policy=policy.default)
    if kind == "mbox":
        for off, ln, data in split_mbox(path):
            try:
                yield folder, rel, f"{off}:{ln}", ln, parse_any(parser, data)
            except Exception as e:      # defekte Mail darf den Import nicht stoppen
                print(f"SKIP {rel}@{off}: {e}", file=sys.stderr, flush=True)
    else:
        with open(path, "rb") as f:
            data = f.read()
        yield folder, rel, None, len(data), parse_any(parser, data)


def worker(tasks, results, base):
    while True:
        task = tasks.get()
        if task is None:
            break
        path, folder, kind = task
        rel = os.path.relpath(path, base)
        try:
            batch = []
            for rec in iter_records(base, path, folder, kind):
                batch.append(rec)
                if len(batch) >= BATCH:
                    results.put(("batch", rel, batch))
                    batch = []
            if batch:
                results.put(("batch", rel, batch))
            results.put(("done", rel, None))
        except Exception as e:
            results.put(("error", rel, str(e)))
    results.put(("exit", None, None))


def run(root: str, workers: int | None = None, base: str | None = None, ctx=None) -> None:
    """Importiert alle Mails unter `root`. Pfade werden relativ zu `base` gespeichert (Standard: root)."""
    from . import jobs
    ctx = ctx or jobs.Ctx()
    db.init()
    conn = db.connect()
    root = os.path.abspath(root)
    base = os.path.abspath(base or root)
    done = {r[0] for r in conn.execute("SELECT source_path FROM import_done")}

    ctx.update(message="Suche Mailboxen …")
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for fn in sorted(names):
            path = os.path.join(dirpath, fn)
            kind = kind_of(path)
            if kind and os.path.relpath(path, base) not in done:
                files.append((path, folder_of(root, path), kind))
    files.sort(key=lambda t: t[0])
    ctx.update(done=0, total=len(files), message=f"{len(files)} Dateien zu importieren")
    ctx.log(f"{len(files)} Dateien zu importieren")
    if not files:
        return

    n_workers = workers or int(os.environ.get("HEXANE_WORKERS", max(1, min(6, (os.cpu_count() or 2) - 1))))
    mpx = mp.get_context("spawn")                         # gleiches Verhalten unter Windows, macOS und Linux
    tasks, results = mpx.Queue(), mpx.Queue(maxsize=16)
    for t in files:
        tasks.put(t)
    for _ in range(n_workers):
        tasks.put(None)
    procs = [mpx.Process(target=worker, args=(tasks, results, base), daemon=True) for _ in range(n_workers)]
    for p in procs:
        p.start()

    exited, n, files_done = 0, 0, 0
    try:
        while exited < n_workers:
            if ctx.cancelled:
                raise jobs.Cancelled()
            try:
                kind, rel, payload = results.get(timeout=1)
            except queue_mod.Empty:
                if not any(p.is_alive() for p in procs):      # Worker abgestürzt: nicht endlos warten
                    break
                continue
            if kind == "exit":
                exited += 1
            elif kind == "batch":
                for folder, src, key, size, m in payload:
                    store(conn, folder, src, key, size, m)
                conn.commit()
                n += len(payload)
                ctx.update(message=f"{files_done}/{len(files)} Dateien, {n} Mails")
            elif kind == "done":
                conn.execute("INSERT OR IGNORE INTO import_done (source_path) VALUES (?)", (rel,))
                conn.commit()
                files_done += 1
                ctx.update(done=files_done, total=len(files), message=f"{files_done}/{len(files)} Dateien, {n} Mails")
                ctx.log(f"[{files_done}/{len(files)}] {rel}  (gesamt {n} Mails)")
            elif kind == "error":
                ctx.log(f"FEHLER {rel}: {payload}")
    finally:
        for p in procs:
            if p.is_alive():
                p.terminate()
        for p in procs:
            p.join(timeout=5)
        conn.commit()
        conn.close()
    ctx.log(f"Fertig: {n} Mails aus {files_done} Dateien")


def load_raw(source_path: str, mbox_key, root: str) -> EmailMessage:
    """Lädt die Original-Mail erneut (für HTML-Ansicht und Anhänge)."""
    base = os.path.abspath(root)
    full = os.path.normpath(os.path.join(base, source_path))
    if not full.startswith(base + os.sep):
        raise ValueError("Pfad ausserhalb des Rohdaten-Verzeichnisses")
    parser = BytesParser(policy=policy.default)
    with open(full, "rb") as f:
        if mbox_key is not None:
            off, ln = (int(x) for x in str(mbox_key).split(":"))
            f.seek(off)
            data = f.read(ln)
            data = data.split(b"\n", 1)[1] if b"\n" in data else b""   # From_-Zeile entfernen
        else:
            data = f.read()
    return parser.parsebytes(data)


def load_raw_bytes(source_path: str, mbox_key, root: str, limit: int = 262144) -> bytes:
    """Nur den Anfang der Original-Mail (Header) lesen, ohne die ganze Mail samt Anhängen zu laden."""
    base = os.path.abspath(root)
    full = os.path.normpath(os.path.join(base, source_path))
    if not full.startswith(base + os.sep):
        raise ValueError("Pfad ausserhalb des Rohdaten-Verzeichnisses")
    with open(full, "rb") as f:
        if mbox_key is not None:
            off, ln = (int(x) for x in str(mbox_key).split(":"))
            f.seek(off)
            data = f.read(min(ln, limit))
            return data.split(b"\n", 1)[1] if b"\n" in data else b""   # From_-Zeile entfernen
        return f.read(limit)


def load_full(source_path: str, mbox_key, root: str, limit: int = 60 * 1024 * 1024) -> tuple[str, bytes]:
    """Die komplette Original-Mail als Bytes (für die Echtheitsprüfung) und die mbox-Trennzeile ('From …')."""
    base = os.path.abspath(root)
    full = os.path.normpath(os.path.join(base, source_path))
    if not full.startswith(base + os.sep):
        raise ValueError("Pfad ausserhalb des Rohdaten-Verzeichnisses")
    with open(full, "rb") as f:
        if mbox_key is None:
            return "", f.read(limit)
        off, ln = (int(x) for x in str(mbox_key).split(":"))
        if ln > limit:
            raise ValueError("Mail zu groß für die Prüfung")
        f.seek(off)
        data = f.read(ln)
    first, _, rest = data.partition(b"\n")
    return first.decode("latin-1").strip(), rest


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Aufruf: python -m app.importer <verzeichnis>")
    run(os.path.abspath(sys.argv[1]))
