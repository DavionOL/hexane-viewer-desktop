from hexane_desk import datasets


def test_detect_demo(demo_data):
    d = datasets.detect(demo_data, fresh=True)
    assert d["exists"] and not d["problems"]
    for part in ("01_EMAIL", "03_DOCUMENTS", "04_TABULAR_DATA", "99_FOR_JOURNALISTS"):
        assert part in d["parts"], part
    assert d["parts"]["01_EMAIL"]["files"] == 3 and d["parts"]["01_EMAIL"]["mailboxes"] == 3
    assert d["parts"]["03_DOCUMENTS"]["files"] == 19
    # doppelt verschachtelte Ordner (01_EMAIL/01_EMAIL) werden aufgelöst
    assert d["parts"]["01_EMAIL"]["path"].endswith("01_EMAIL/01_EMAIL") or d["parts"]["01_EMAIL"]["path"].endswith("01_EMAIL\\01_EMAIL")


def test_detect_problems(tmp_path):
    assert datasets.detect(tmp_path / "gibtsnicht", fresh=True)["problems"]
    (tmp_path / "01_EMAIL.tar").write_bytes(b"x")
    d = datasets.detect(tmp_path, fresh=True)
    assert d["tars"] and any("entpacken" in p.lower() for p in d["problems"])


def test_capabilities_keys():
    assert set(datasets.capabilities()) == {"pdftotext", "pdftoppm", "tesseract", "catdoc"}
