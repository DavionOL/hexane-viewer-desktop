"""Findet optionale externe Hilfsprogramme (Poppler, Tesseract, catdoc).

Gesucht wird im Systempfad und in den Ordnern `tools/` neben dem Programm (vom Windows-Installer angelegt) und im Benutzerprofil.
Zusätzliche Suchordner lassen sich mit der Umgebungsvariablen HEXANE_TOOLS (durch den Pfadtrenner getrennt) angeben.
"""
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from . import config

MAX_DEPTH = 5


def tool_dirs() -> list[Path]:
    dirs: list[Path] = []
    for p in os.environ.get("HEXANE_TOOLS", "").split(os.pathsep):
        if p:
            dirs.append(Path(p))
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent / "tools")
    dirs.append(config.config_dir() / "tools")
    return dirs


@lru_cache(maxsize=None)
def find(name: str) -> str | None:
    """Pfad zum Programm oder None."""
    exe = name + (".exe" if os.name == "nt" else "")
    for base in tool_dirs():                     # mitgelieferte Programme haben Vorrang vor dem Systempfad
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for dp, dirs, files in os.walk(base):
            if len(Path(dp).parts) - base_depth >= MAX_DEPTH:
                dirs[:] = []
            if exe in files:
                return os.path.join(dp, exe)
    return shutil.which(name)


def env_for(path: str | None) -> dict | None:
    """Umgebung für Tesseract: Sprachdaten (`tessdata`) neben dem Programm verwenden, falls vorhanden."""
    if not path:
        return None
    td = Path(path).parent / "tessdata"
    if td.is_dir():
        return {**os.environ, "TESSDATA_PREFIX": str(td)}
    return None
