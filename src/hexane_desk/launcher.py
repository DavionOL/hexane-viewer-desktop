"""Start per Klick: Programm-Starter (Linux), Einzelinstanz und Beenden, wenn der Browser-Tab geschlossen wird."""
import json
import os
import shlex
import socket
import sys
import time
import webbrowser
from pathlib import Path

from . import config

IDLE_SECONDS = 150       # so lange darf der Browser schweigen (Tabs im Hintergrund melden sich nur etwa einmal pro Minute)
FIRST_PING_SECONDS = 180  # so lange wartet das Programm auf das erste Lebenszeichen der Seite

ICON_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#1f3a5f"/>
  <circle cx="54" cy="54" r="26" fill="none" stroke="#fff" stroke-width="10"/>
  <path d="M74 74 L102 102" stroke="#fff" stroke-width="12" stroke-linecap="round"/>
</svg>
"""


def running_file() -> Path:
    return config.config_dir() / "running.json"


def _alive(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_running() -> str | None:
    """Link einer bereits laufenden Instanz (damit ein zweiter Klick nur den Browser öffnet)."""
    try:
        info = json.loads(running_file().read_text(encoding="utf-8"))
        if _alive(int(info["port"])):
            return info["url"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def remember(url: str, port: int) -> None:
    f = running_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"url": url, "port": port, "pid": os.getpid()}), encoding="utf-8")
    try:
        f.chmod(0o600)               # enthält das Zugriffstoken
    except OSError:
        pass


def forget() -> None:
    try:
        running_file().unlink()
    except OSError:
        pass


def wait_until_closed(state: dict, busy) -> None:
    """Blockiert, bis der Browser-Tab zu ist. Laufende Einrichtungsschritte halten das Programm am Leben."""
    started = time.time()
    while True:
        time.sleep(1)
        if busy():
            continue
        last = state.get("last_ping")
        if last is None:
            if time.time() - started > FIRST_PING_SECONDS:
                return
        elif time.time() - last > IDLE_SECONDS:
            return


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "launch"]
    return [sys.executable, "-m", "hexane_desk", "launch"]


def install_linux() -> str:
    """Legt Starter und Symbol im Benutzerprofil an (Anwendungsmenü, per Rechtsklick auch auf den Desktop ziehbar)."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon = data / "icons" / "hicolor" / "scalable" / "apps" / "hexane-desk.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON_SVG, encoding="utf-8")
    apps = data / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "hexane-desk.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Hexane Desk\nGenericName=Recherche-Werkzeug\n"
        "Comment=Volltextsuche im hexane-Datensatz (lokal, öffnet den Browser)\n"
        f"Exec={' '.join(shlex.quote(c) for c in _command())}\nIcon={icon}\nTerminal=false\n"
        "Categories=Office;Utility;\nKeywords=Recherche;Mail;Suche;hexane;\nStartupNotify=false\n", encoding="utf-8")
    entry.chmod(0o755)
    try:
        os.system(f"update-desktop-database {shlex.quote(str(apps))} >/dev/null 2>&1")
    except OSError:
        pass
    return str(entry)
