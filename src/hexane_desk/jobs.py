"""Hintergrund-Jobs: Import und Auswertungen laufen im Programm, mit Fortschritt, Abbruch und Fortsetzen.

Jeder Schritt ist wiederholbar und setzt nach Abbruch dort fort, wo er war (Importer und Dokumente merken sich fertige
Dateien in der Datenbank). Es läuft immer nur ein Schritt zugleich, weil alle in dieselbe Datenbank schreiben.
"""
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, datasets, db


class Cancelled(Exception):
    pass


class Ctx:
    """Verbindung zwischen einem laufenden Schritt und der Anzeige (Fortschritt, Abbruch, Protokoll)."""

    def __init__(self, job: "Job | None" = None):
        self.job = job

    def update(self, done=None, total=None, message=None):
        j = self.job
        if j is None:
            if message:
                print(message, flush=True)
            return
        if done is not None:
            j.done = done
        if total is not None:
            j.total = total
        if message:
            j.message = message

    def log(self, line: str = "", **_ignored):
        if self.job is not None:
            self.job.log.append(line)
        else:
            print(line, flush=True)

    @property
    def cancelled(self) -> bool:
        return bool(self.job and self.job.cancel_event.is_set())

    def check(self):
        if self.cancelled:
            raise Cancelled()


@dataclass
class Job:
    step: str
    status: str = "running"          # running | done | failed | cancelled
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def view(self) -> dict:
        return {"step": self.step, "status": self.status, "done": self.done, "total": self.total,
                "message": self.message, "error": self.error, "started": self.started, "finished": self.finished,
                "log": list(self.log)[-15:]}


@dataclass
class Step:
    key: str
    label: str
    desc: str
    run: Callable[[Ctx], str | None]
    part: str | None = None          # benötigter Teil des Datensatzes
    needs: tuple = ()                # Schritte, die vorher gelaufen sein sollten
    tool: tuple = ()                 # benötigte optionale Hilfsprogramme (datasets.capabilities)
    net: bool = False                # braucht Internet und die Zustimmung des Nutzers
    optional: bool = False


def _part(name: str) -> Path:
    root = config.data_root()
    if not root:
        raise RuntimeError("Es ist noch kein Datenordner gewählt.")
    p = datasets.detect(root)["parts"].get(name)
    if not p:
        raise RuntimeError(f"Teil {name} wurde im Datenordner nicht gefunden.")
    return Path(p["path"])


def _mails(ctx):
    from . import importer
    importer.run(str(_part("01_EMAIL")), base=str(config.data_root()), ctx=ctx)


def _docs(ctx):
    from . import docs
    docs.run(str(_part("03_DOCUMENTS")), base=str(config.data_root()), ctx=ctx)


def _ocr(ctx):
    from . import docs
    docs.run_ocr(str(_part("03_DOCUMENTS")), base=str(config.data_root()), ctx=ctx)


def _docmeta(ctx):
    from . import docmeta
    docmeta.main(str(_part("04_TABULAR_DATA")), ctx=ctx)


def _lists(ctx):
    from . import lists
    lists.fetch_all(ctx=ctx)


def _people(ctx):
    from . import people
    people.main(ctx=ctx)


def _junk(ctx):
    from . import junk
    junk.main(ctx=ctx)


def _donations(ctx):
    from . import donations
    donations.main(ctx=ctx)


STEPS: dict[str, Step] = {s.key: s for s in [
    Step("mails", "Mails einlesen", "Liest alle Mailboxen in den Suchindex (dauert bei 210 GB mehrere Stunden, kann unterbrochen werden).",
         _mails, part="01_EMAIL"),
    Step("docs", "Dokumente erfassen", "Liest den Text aus PDF-, Office- und Textdateien.", _docs, part="03_DOCUMENTS"),
    Step("docmeta", "Dokument-Metadaten", "Übernimmt Art, Datum und Herkunft der Dokumente aus den Tabellen des Datensatzes.",
         _docmeta, part="04_TABULAR_DATA", needs=("docs",)),
    Step("ocr", "Scans per OCR lesen", "Erkennt Text in gescannten PDFs. Sehr langsam, braucht Tesseract und Poppler.",
         _ocr, part="03_DOCUMENTS", needs=("docs",), tool=("tesseract", "pdftoppm"), optional=True),
    Step("lists", "Referenzlisten laden", "Lädt öffentliche Listen (Politiker von abgeordnetenwatch.de, Behörden von FragDenStaat). "
         "Braucht Internet und deine Zustimmung.", _lists, net=True, optional=True),
    Step("people", "Adressen auswerten", "Ordnet Adressen in Stufen ein (öffentliche Akteure, Parteidomains, Rest nur je Domain).",
         _people, needs=("mails",)),
    Step("junk", "Trash-Gruppen", "Ordnet Mails Gruppen wie Zustellfehler, Newsletter, Benachrichtigungen zu, damit sie sich ausblenden lassen.",
         _junk, needs=("mails",)),
    Step("donations", "Spenden-Übersicht", "Liest Datum und Betrag aus PayPal-Spendenmeldungen (keine Namen).",
         _donations, needs=("mails",), optional=True),
]}
RECOMMENDED = ["mails", "docs", "docmeta", "lists", "people", "junk", "donations"]

_current: Job | None = None
_jobs: dict[str, Job] = {}
_mgr_lock = threading.Lock()


def persisted() -> dict:
    try:
        conn = db.connect()
        rows = conn.execute("SELECT name, status, finished_ts, info FROM steps").fetchall()
        conn.close()
        return {r["name"]: dict(r) for r in rows}
    except Exception:
        return {}


def _persist(step: str, status: str, info: str = ""):
    try:
        db.init()
        conn = db.connect()
        conn.execute("INSERT OR REPLACE INTO steps (name, status, finished_ts, info) VALUES (?,?,?,?)",
                     (step, status, int(time.time()), info))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _execute(job: Job, step: Step):
    global _current
    ctx = Ctx(job)
    try:
        info = step.run(ctx) or ""
        job.status = "done"
        _persist(step.key, "done", str(info))
    except Cancelled:
        job.status = "cancelled"
        _persist(step.key, "cancelled", "abgebrochen")
    except Exception as e:                                   # Fehler anzeigen, nicht abstürzen
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}"
        job.log.append(traceback.format_exc()[-1500:])
        _persist(step.key, "failed", job.error)
    finally:
        job.finished = time.time()
        with _mgr_lock:
            _current = None


def availability(step: Step, done: dict, caps: dict, parts: dict) -> tuple[bool, str]:
    """(verfügbar, Grund)"""
    if step.part and step.part not in parts:
        return False, f"Teil {step.part} nicht gefunden"
    for t in step.tool:
        if not caps.get(t):
            return False, f"Hilfsprogramm {t} nicht installiert"
    if step.net and not config.settings().lists_consent:
        return False, "Internetzugriff nicht erlaubt (in der Einrichtung zustimmen)"
    for n in step.needs:
        if done.get(n, {}).get("status") != "done" and not (n == "docs" and step.key == "ocr" and False):
            return False, f"zuerst: {STEPS[n].label}"
    return True, ""


def start(key: str) -> Job:
    global _current
    if key not in STEPS:
        raise KeyError(key)
    step = STEPS[key]
    with _mgr_lock:
        if _current is not None and _current.status == "running":
            raise RuntimeError(f"Es läuft bereits ein Schritt ({STEPS[_current.step].label}).")
        job = Job(step=key)
        _jobs[key] = job
        _current = job
    db.init()
    threading.Thread(target=_execute, args=(job, step), daemon=True, name=f"job-{key}").start()
    return job


def start_sequence(keys: list[str]) -> Job:
    """Startet mehrere Schritte nacheinander; nicht verfügbare oder bereits erledigte werden übersprungen."""
    seq_ctx = {"keys": keys}

    def run_all(ctx: Ctx):
        for k in seq_ctx["keys"]:
            ctx.check()
            st = STEPS[k]
            ok, why = availability(st, persisted(), datasets.capabilities(),
                                   datasets.detect(config.data_root())["parts"] if config.data_root() else {})
            if not ok or persisted().get(k, {}).get("status") == "done":
                ctx.log(f"übersprungen: {st.label} ({why or 'bereits erledigt'})")
                continue
            ctx.update(message=f"Schritt: {st.label}")
            st.run(ctx)
            _persist(k, "done", "")
            ctx.log(f"fertig: {st.label}")

    global _current
    with _mgr_lock:
        if _current is not None and _current.status == "running":
            raise RuntimeError(f"Es läuft bereits ein Schritt ({STEPS[_current.step].label}).")
        job = Job(step="all")
        _jobs["all"] = job
        _current = job
    db.init()
    step = Step("all", "Alle empfohlenen Schritte", "", run_all)
    threading.Thread(target=_execute, args=(job, step), daemon=True, name="job-all").start()
    return job


def cancel() -> bool:
    with _mgr_lock:
        if _current is not None and _current.status == "running":
            _current.cancel_event.set()
            _current.message = "Abbruch angefordert …"
            return True
    return False


def running() -> Job | None:
    return _current if (_current is not None and _current.status == "running") else None


def overview() -> dict:
    root = config.data_root()
    parts = datasets.detect(root)["parts"] if root else {}
    caps = datasets.capabilities()
    done = persisted()
    steps = []
    for s in STEPS.values():
        ok, why = availability(s, done, caps, parts)
        st = done.get(s.key, {})
        steps.append({"key": s.key, "label": s.label, "desc": s.desc, "optional": s.optional, "available": ok,
                      "reason": why, "status": st.get("status", ""), "finished_ts": st.get("finished_ts"),
                      "info": st.get("info", "")})
    return {"steps": steps, "jobs": {k: j.view() for k, j in _jobs.items()}, "running": (running().step if running() else None),
            "capabilities": caps, "recommended": RECOMMENDED}
