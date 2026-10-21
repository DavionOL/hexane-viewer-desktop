"""Erkennt, welche Teile des hexane-Datensatzes unterhalb eines gewählten Ordners liegen.

Der Datensatz hat folgende Teile (jeweils auch doppelt verschachtelt, z. B. 01_EMAIL/01_EMAIL/<postfach>/part-01.mbox):
01_EMAIL, 02_DATABASES, 03_DOCUMENTS, 04_TABULAR_DATA, 05_CREDENTIALS_AND_KEYS, 06_MEDIA, 99_FOR_JOURNALISTS, _root.
"""
import os
from pathlib import Path

PARTS = ["01_EMAIL", "02_DATABASES", "03_DOCUMENTS", "04_TABULAR_DATA", "06_MEDIA", "99_FOR_JOURNALISTS"]
MAX_DEPTH = 4


def _find_dir(root: Path, name: str) -> Path | None:
    """Sucht ein Verzeichnis mit diesem Namen (Breitensuche, begrenzte Tiefe) und steigt in gleichnamige Unterordner ab."""
    queue = [(root, 0)]
    while queue:
        cur, depth = queue.pop(0)
        try:
            entries = sorted(os.scandir(cur), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if e.name == name:
                    p = Path(e.path)
                    while (p / name).is_dir():          # 01_EMAIL/01_EMAIL
                        p = p / name
                    return p
                if depth + 1 < MAX_DEPTH:
                    queue.append((Path(e.path), depth + 1))
    return None


def _walk_stats(path: Path, suffixes: tuple[str, ...] | None = None) -> tuple[int, int]:
    n = size = 0
    for dp, _dirs, files in os.walk(path):
        for f in files:
            if suffixes and not f.lower().endswith(suffixes):
                continue
            n += 1
            try:
                size += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return n, size


_cache: dict = {}


def invalidate() -> None:
    _cache.clear()


def detect(root: str | Path, fresh: bool = False, ttl: float = 120.0) -> dict:
    """Erkennung mit kurzem Zwischenspeicher (das Durchsuchen großer Ordner dauert)."""
    import time
    key = str(root)
    hit = _cache.get(key)
    if hit and not fresh and time.time() - hit[0] < ttl:
        return hit[1]
    val = _detect(root)
    _cache[key] = (time.time(), val)
    return val


def _detect(root: str | Path) -> dict:
    root = Path(root)
    out: dict = {"root": str(root), "exists": root.is_dir(), "parts": {}, "tars": [], "problems": [], "ready_steps": []}
    if not root.is_dir():
        out["problems"].append("Der Ordner existiert nicht oder ist nicht lesbar.")
        return out

    for name in PARTS:
        p = _find_dir(root, name)
        if p:
            suffixes = (".mbox", ".eml") if name == "01_EMAIL" else None
            n, size = _walk_stats(p, suffixes)
            part = {"path": str(p), "files": n, "bytes": size}
            if name == "01_EMAIL":
                part["mailboxes"] = len([d for d in p.iterdir() if d.is_dir()]) if p.is_dir() else 0
            out["parts"][name] = part

    # gepackte Archive: ohne Entpacken lässt sich der Datensatz noch nicht auswerten
    try:
        for e in os.scandir(root):
            if e.is_file() and e.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
                out["tars"].append({"name": e.name, "bytes": e.stat().st_size})
    except OSError:
        pass
    if out["tars"] and not out["parts"]:
        out["problems"].append("Es liegen nur gepackte Archive (.tar) vor. Bitte zuerst entpacken (siehe Anleitung).")
    if not out["parts"] and not out["tars"]:
        out["problems"].append("Im gewählten Ordner wurde kein Datensatz gefunden (erwartet: 01_EMAIL, 03_DOCUMENTS, …).")

    manifest = None
    for cand in ("_root", ""):
        d = root / cand if cand else root
        for sub in (d, d / "_root"):
            m = sub / "MANIFEST.tsv"
            if m.is_file():
                manifest = str(m)
    out["manifest"] = manifest
    return out


def capabilities() -> dict:
    """Optionale Hilfsprogramme: verbessern Qualität oder Geschwindigkeit, sind aber nicht nötig."""
    from . import tools
    return {n: bool(tools.find(n)) for n in ("pdftotext", "pdftoppm", "tesseract", "catdoc")}
