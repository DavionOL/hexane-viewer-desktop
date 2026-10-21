import json
import os

os.environ["HEXANE_NO_POPPLER"] = "1"          # Tests nutzen den reinen Python-Weg für PDFs (läuft überall)
os.environ.setdefault("HEXANE_WORKERS", "2")

import pytest

from hexane_desk import config, datasets, demo, jobs


@pytest.fixture(scope="session")
def demo_data(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    demo.make(d, n_mails=120)
    return d


@pytest.fixture()
def desk(tmp_path, monkeypatch, demo_data):
    """Frisches Benutzerprofil (Konfiguration + Index) mit gewähltem Demo-Datenordner."""
    monkeypatch.setenv("HEXANE_DESK_HOME", str(tmp_path / "home"))
    config._cache = None
    datasets.invalidate()
    jobs._jobs.clear()
    jobs._current = None
    config.save(data_dir=str(demo_data), party_patterns="partei-beispiel|landesverband-beispiel")
    config.lists_dir().mkdir(parents=True, exist_ok=True)
    (config.lists_dir() / "officials.json").write_text(json.dumps({"officials": [
        {"name": "Anna Beispiel", "first_name": "Anna", "last_name": "Beispiel", "url": "https://beispiel.example/anna", "mandates": []},
        {"name": "Bernd Muster", "first_name": "Bernd", "last_name": "Muster", "url": "https://beispiel.example/bernd", "mandates": []}]}),
        encoding="utf-8")
    from hexane_desk import db
    db.init()
    return tmp_path


@pytest.fixture()
def indexed(desk):
    """Index nach allen Schritten, die ohne Internet und ohne OCR laufen."""
    for key in ["mails", "docs", "docmeta", "people", "junk", "donations"]:
        jobs.STEPS[key].run(jobs.Ctx())
        jobs._persist(key, "done", "")
    return desk
