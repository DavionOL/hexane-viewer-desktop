"""Textextraktion für Dokumente (PDF, Office, OpenDocument, RTF, Text) in den Suchindex.

Wird über die Einrichtung im Programm (oder `hexane-desk index`) gestartet.

Die Rohdateien werden nur gelesen. Jede Datei bekommt einen Eintrag (auch Formate ohne Textextraktion,
damit der Dateiname durchsuchbar ist). Ein erneuter Aufruf überspringt bereits erfasste Dateien.
"""
import functools
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from html import unescape

from . import db, tools

TEXT_LIMIT = 2_000_000          # Zeichen je Dokument im Index
ZIP_MEMBER_LIMIT = 50_000_000   # Bytes je Zip-Eintrag (Schutz vor Zip-Bomben)
MAX_OCR_PAGES = 40
MIN_TEXT_CHARS = 30             # weniger Zeichen in einer PDF -> vermutlich Scan

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\v]+")
_NEWLINES = re.compile(r"\n\s*\n+")


# ---------- Extraktion je Format ----------

def clean(text: str) -> str:
    text = text.replace("\f", "\n")
    text = _SPACES.sub(" ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return _NEWLINES.sub("\n\n", text).strip()


def xml_text(xml: str, breaks=()) -> str:
    for b in breaks:
        xml = xml.replace(b, "\n")
    return unescape(_TAG.sub(" ", xml))


def zread(z: zipfile.ZipFile, name: str) -> str:
    with z.open(name) as f:
        return f.read(ZIP_MEMBER_LIMIT).decode("utf-8", "replace")


def from_docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist()
                 if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n)]
        return "\n".join(xml_text(zread(z, n), ("</w:p>",)) for n in names)


def from_xlsx(path: str) -> str:
    """Zellen mit Text (gemeinsame und Inline-Strings). Reine Zahlenzellen werden nicht indexiert."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = []
        if "xl/sharedStrings.xml" in names:
            parts.append(xml_text(zread(z, "xl/sharedStrings.xml"), ("</si>",)))
        for n in names:
            if re.fullmatch(r"xl/worksheets/[^/]+\.xml", n):
                parts.extend(xml_text(m) for m in re.findall(r"<is>(.*?)</is>", zread(z, n), re.S))
        return "\n".join(parts)


def from_pptx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/(slides|notesSlides)/[^/]+\.xml", n))
        return "\n".join(xml_text(zread(z, n), ("</a:p>",)) for n in names)


def from_odf(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        return xml_text(zread(z, "content.xml"),
                        ("</text:p>", "</text:h>", "</table:table-row>", "<text:line-break/>"))


def from_rtf(path: str) -> str:
    with open(path, "rb") as f:
        s = f.read(ZIP_MEMBER_LIMIT).decode("cp1252", "replace")
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), s)
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\{\\\*[^{}]*\}", "", s)
    s = re.sub(r"\\pard?|\\line", "\n", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    return re.sub(r"[{}]", "", s)


def from_plain(path: str) -> str:
    with open(path, "rb") as f:
        return f.read(ZIP_MEMBER_LIMIT).decode("utf-8", "replace")


def from_html(path: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", from_plain(path))
    return xml_text(html)


def run_cmd(cmd: list[str], timeout: int = 120, env: dict | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


PDFTOTEXT = None if os.environ.get("HEXANE_NO_POPPLER") else tools.find("pdftotext")   # Schalter für Tests
CATDOC, XLS2CSV, CATPPT = (tools.find(n) for n in ("catdoc", "xls2csv", "catppt"))
MAX_PDF_PAGES = 400


def from_pdf_py(path: str) -> str:
    """PDF-Text ohne externe Programme (pypdf). Langsamer als Poppler, dafür überall lauffähig."""
    import logging
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    from pypdf import PdfReader
    out = []
    for i, page in enumerate(PdfReader(path, strict=False).pages):
        if i >= MAX_PDF_PAGES:
            break
        out.append(page.extract_text() or "")
    return "\f".join(out) + "\f"


def from_pdf(path: str) -> str:
    if PDFTOTEXT:
        return run_cmd([PDFTOTEXT, "-layout", "-enc", "UTF-8", path, "-"])
    return from_pdf_py(path)


EXTRACTORS = {
    "pdf": from_pdf,
    "docx": from_docx, "xlsx": from_xlsx, "pptx": from_pptx,
    "odt": from_odf, "ods": from_odf, "odp": from_odf,
    "rtf": from_rtf,
    "doc": lambda p: run_cmd([CATDOC, "-d", "utf-8", p]) if CATDOC else "",
    "xls": lambda p: run_cmd([XLS2CSV, "-d", "utf-8", p]) if XLS2CSV else "",
    "ppt": lambda p: run_cmd([CATPPT, "-d", "utf-8", p]) if CATPPT else "",
    "txt": from_plain, "csv": from_plain, "tsv": from_plain, "md": from_plain,
    "html": from_html, "htm": from_html,
}


def extract(base: str, path: str) -> dict:
    rel = os.path.relpath(path, base)
    name = os.path.basename(path)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        st = os.stat(path)
        size, mtime = st.st_size, int(st.st_mtime)
    except OSError:
        size, mtime = 0, None

    text, error = "", None
    fn = EXTRACTORS.get(ext)
    if fn:
        try:
            text = fn(path)
        except Exception as e:      # defekte Datei darf den Lauf nicht stoppen
            error = str(e)
    pages = text.count("\f") if ext == "pdf" else 0
    text = clean(text)[:TEXT_LIMIT]
    ocr = 1 if ext == "pdf" and len(re.sub(r"\s", "", text)) < MIN_TEXT_CHARS else 0
    return {"path": rel, "name": name, "ext": ext, "size": size, "mtime": mtime, "pages": pages,
            "preview": _SPACES.sub(" ", text[:300].replace("\n", " ")).strip()[:200],
            "text": text, "ocr_status": ocr, "error": error}


# ---------- Datenbank ----------

def store(conn, d: dict) -> None:
    cur = conn.execute(
        "INSERT OR IGNORE INTO documents (path, name, ext, size, mtime, pages, preview, text, ocr_status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (d["path"], d["name"], d["ext"], d["size"], d["mtime"], d["pages"],
         d["preview"], d["text"], d["ocr_status"]))
    if cur.rowcount:
        conn.execute("INSERT INTO documents_fts (rowid, name, body) VALUES (?,?,?)",
                     (cur.lastrowid, d["name"], d["text"]))


def n_workers() -> int:
    return int(os.environ.get("HEXANE_WORKERS", max(1, min(6, (os.cpu_count() or 2) - 1))))


def run(root: str, base: str | None = None, ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    db.init()
    conn = db.connect()
    root = os.path.abspath(root)
    base = os.path.abspath(base or root)
    done = {r[0] for r in conn.execute("SELECT path FROM documents")}
    ctx.update(message="Suche Dokumente …")
    todo = []
    for dirpath, _dirs, names in os.walk(root):
        for fn in names:
            p = os.path.join(dirpath, fn)
            if os.path.relpath(p, base) not in done:
                todo.append(p)
    todo.sort()
    ctx.update(done=0, total=len(todo), message=f"{len(todo)} Dateien zu erfassen")
    n = errors = 0
    mpx = mp.get_context("spawn")
    pool = mpx.Pool(n_workers())
    try:
        for d in pool.imap_unordered(functools.partial(extract, base), todo, chunksize=4):
            if ctx.cancelled:
                raise jobs.Cancelled()
            store(conn, d)
            n += 1
            if d["error"]:
                errors += 1
                ctx.log(f"FEHLER {d['path']}: {d['error']}")
            if n % 200 == 0:
                conn.commit()
                ctx.update(done=n, total=len(todo), message=f"{n}/{len(todo)} Dateien")
    finally:
        pool.terminate()
        pool.join()
        conn.commit()
    need = conn.execute("SELECT COUNT(*) FROM documents WHERE ocr_status = 1").fetchone()[0]
    conn.close()
    ctx.update(done=n, total=len(todo))
    ctx.log(f"Fertig: {n} Dateien ({errors} Fehler). Scans ohne Text (OCR nötig): {need}")


# ---------- OCR (optional, braucht Tesseract und Poppler) ----------

def ocr_one(args) -> tuple[int, str]:
    base, doc_id, rel = args
    tmp = tempfile.mkdtemp(prefix="ocr-")
    try:
        path = os.path.join(base, rel)
        # lange Seitenkante auf 2600 px begrenzen (A4 ca. 220 dpi); verhindert riesige Bilder bei Plakaten/Plänen
        pdftoppm, tesseract = tools.find("pdftoppm"), tools.find("tesseract")
        if not pdftoppm or not tesseract:
            return doc_id, ""
        run_cmd([pdftoppm, "-scale-to", "2600", "-gray", "-png", "-l", str(MAX_OCR_PAGES), path,
                 os.path.join(tmp, "p")], timeout=600)
        texts = []
        for f in sorted(os.listdir(tmp)):
            texts.append(run_cmd([tesseract, os.path.join(tmp, f), "-", "-l", "deu+eng"], timeout=300, env=tools.env_for(tesseract)))
        return doc_id, clean("\n".join(texts))[:TEXT_LIMIT]
    except Exception:
        return doc_id, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_ocr(root: str, base: str | None = None, ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    os.environ["OMP_THREAD_LIMIT"] = "1"        # ein Thread je Tesseract, Parallelität über Prozesse
    db.init()
    conn = db.connect()
    base = os.path.abspath(base or root)
    rows = conn.execute("SELECT id, path FROM documents WHERE ocr_status = 1 ORDER BY id").fetchall()
    ctx.update(done=0, total=len(rows), message=f"{len(rows)} Scans für OCR")
    n = 0
    mpx = mp.get_context("spawn")
    pool = mpx.Pool(max(1, n_workers() // 2))        # OCR ist speicherhungrig: weniger Prozesse als sonst
    try:
        for doc_id, text in pool.imap_unordered(ocr_one, [(base, r["id"], r["path"]) for r in rows]):
            if ctx.cancelled:
                raise jobs.Cancelled()
            preview = _SPACES.sub(" ", text[:300].replace("\n", " ")).strip()[:200]
            conn.execute("UPDATE documents SET text = ?, preview = ?, ocr_status = ? WHERE id = ?",
                         (text, preview, 2 if text else 3, doc_id))
            conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
            name = conn.execute("SELECT name FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
            conn.execute("INSERT INTO documents_fts (rowid, name, body) VALUES (?,?,?)", (doc_id, name, text))
            n += 1
            conn.commit()                        # kurze Transaktionen, damit andere Prozesse schreiben können
            if n % 5 == 0:
                ctx.update(done=n, total=len(rows), message=f"OCR {n}/{len(rows)}")
    finally:
        pool.terminate()
        pool.join()
        conn.commit()
        conn.close()
    ctx.log(f"Fertig: {n} Scans")
