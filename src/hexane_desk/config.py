"""Einstellungen und Pfade, plattformunabhängig (Windows, macOS, Linux).

Konfiguration und Index liegen im Benutzerprofil. Für Tests und portablen Betrieb lässt sich alles mit der
Umgebungsvariablen HEXANE_DESK_HOME in einen Ordner umleiten.
"""
import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP = "hexane-desk"
_lock = threading.Lock()


@dataclass
class Settings:
    data_dir: str = ""            # Wurzelordner des (entpackten) Datensatzes
    index_dir: str = ""           # leer = Standardort im Benutzerprofil
    port: int = 8480
    mask_external: bool = True    # MCP: Adressen Außenstehender maskieren
    allow_write: bool = False     # MCP: Schreib-Werkzeuge (Markierungen) erlauben
    lists_consent: bool = False   # Listen (abgeordnetenwatch, FragDenStaat) dürfen aus dem Internet geladen werden
    party_patterns: str = "afd|alternativefuer|alternative-fuer"   # reguläres Muster für Domains der Partei (Stufe 2)


def home() -> Path | None:
    h = os.environ.get("HEXANE_DESK_HOME")
    return Path(h) if h else None


def config_dir() -> Path:
    h = home()
    return (h / "config") if h else Path(user_config_dir(APP, appauthor=False))


def default_index_dir() -> Path:
    h = home()
    return (h / "index") if h else Path(user_data_dir(APP, appauthor=False)) / "index"


def lists_dir() -> Path:
    """Benutzerpflegbare Listen (junk_domains.txt, extra_public_figures.txt) und geladene Referenzlisten."""
    return config_dir() / "lists"


def settings_file() -> Path:
    return config_dir() / "settings.json"


_cache: Settings | None = None


def settings(reload: bool = False) -> Settings:
    global _cache
    with _lock:
        if _cache is None or reload:
            s = Settings()
            try:
                data = json.loads(settings_file().read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except (OSError, ValueError):
                pass
            _cache = s
        return _cache


def save(**changes) -> Settings:
    s = settings()
    for k, v in changes.items():
        if hasattr(s, k):
            setattr(s, k, v)
    settings_file().parent.mkdir(parents=True, exist_ok=True)
    settings_file().write_text(json.dumps(asdict(s), indent=2, ensure_ascii=False), encoding="utf-8")
    return s


def data_root() -> Path | None:
    d = settings().data_dir
    return Path(d) if d else None


def index_dir() -> Path:
    d = settings().index_dir
    return Path(d) if d else default_index_dir()


def index_path() -> Path:
    return index_dir() / "index.sqlite"


def ensure_lists_templates() -> None:
    """Legt die benutzerpflegbaren Listen beim ersten Start an (Vorlagen aus dem Paket)."""
    d = lists_dir()
    d.mkdir(parents=True, exist_ok=True)
    tpl = Path(__file__).parent / "templates"
    for name in ("junk_domains.txt", "extra_public_figures.txt"):
        target = d / name
        if not target.exists() and (tpl / name).exists():
            target.write_text((tpl / name).read_text(encoding="utf-8"), encoding="utf-8")


# Zugriffstoken dieses Programmlaufs: schützt den lokalen Server vor anderen Webseiten (DNS-Rebinding, CSRF)
TOKEN = secrets.token_urlsafe(24)
