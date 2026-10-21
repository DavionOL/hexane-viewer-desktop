import os
import stat

from hexane_desk import datasets, tools


def _fake_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho ok\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_find_in_tools_dir(tmp_path, monkeypatch):
    name = "fake-pdftool"
    _fake_exe(tmp_path / "poppler" / "pkg" / "Library" / "bin" / (name + (".exe" if os.name == "nt" else "")))
    monkeypatch.setenv("HEXANE_TOOLS", str(tmp_path))
    tools.find.cache_clear()
    p = tools.find(name)
    assert p and os.path.basename(p).startswith(name)
    assert tools.find("gibt-es-nicht-xyz") is None


def test_env_for_tessdata(tmp_path):
    exe = tmp_path / "tesseract.exe"
    exe.write_text("x")
    assert tools.env_for(str(exe)) is None
    (tmp_path / "tessdata").mkdir()
    assert tools.env_for(str(exe))["TESSDATA_PREFIX"] == str(tmp_path / "tessdata")
    assert tools.env_for(None) is None


def test_capabilities_use_tools(tmp_path, monkeypatch):
    _fake_exe(tmp_path / ("catdoc" + (".exe" if os.name == "nt" else "")))
    monkeypatch.setenv("HEXANE_TOOLS", str(tmp_path))
    tools.find.cache_clear()
    assert datasets.capabilities()["catdoc"] is True
    tools.find.cache_clear()
