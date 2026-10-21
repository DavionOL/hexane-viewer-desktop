import time

from hexane_desk import launcher


def test_beenden_nach_stille(monkeypatch):
    monkeypatch.setattr(launcher, "IDLE_SECONDS", 1)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    state = {"last_ping": time.time() - 5}
    launcher.wait_until_closed(state, lambda: False)        # kehrt zurück, weil das letzte Lebenszeichen zu alt ist


def test_laufende_schritte_halten_am_leben(monkeypatch):
    monkeypatch.setattr(launcher, "IDLE_SECONDS", 0)
    calls = {"n": 0}

    def busy():
        calls["n"] += 1
        return calls["n"] < 4

    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    launcher.wait_until_closed({"last_ping": time.time() - 99}, busy)
    assert calls["n"] == 4


def test_einzelinstanz(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXANE_DESK_HOME", str(tmp_path))
    assert launcher.find_running() is None
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); port = s.getsockname()[1]
    launcher.remember(f"http://127.0.0.1:{port}/?t=x", port)
    assert launcher.find_running().endswith("t=x")
    s.close()
    assert launcher.find_running() is None                  # nichts hört mehr zu: veralteter Eintrag
    launcher.forget()


def test_starter_datei(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = launcher.install_linux()
    text = open(path, encoding="utf-8").read()
    assert "Exec=" in text and "launch" in text and "Terminal=false" in text
    assert (tmp_path / "icons/hicolor/scalable/apps/hexane-desk.svg").exists()
