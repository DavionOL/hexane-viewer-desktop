import threading

import pytest

from hexane_desk import db, importer, jobs


def q(sql, *a):
    c = db.connect()
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def test_counts_and_resume(indexed):
    assert q("SELECT COUNT(*) FROM messages")[0][0] == 120
    assert q("SELECT COUNT(*) FROM documents")[0][0] == 19
    assert len(q("SELECT DISTINCT folder FROM messages")) == 3
    # erneuter Lauf: nichts doppelt
    jobs.STEPS["mails"].run(jobs.Ctx())
    assert q("SELECT COUNT(*) FROM messages")[0][0] == 120


def test_documents(indexed):
    pdf = q("SELECT text, ocr_status FROM documents WHERE ext = 'pdf' AND ocr_status = 0")
    assert pdf and "Demo-Dokument" in pdf[0]["text"]                 # Text per pypdf gelesen
    assert q("SELECT COUNT(*) FROM documents WHERE ocr_status = 1")[0][0] == 1   # „Scan“ ohne Textebene
    assert q("SELECT COUNT(*) FROM documents WHERE genre IS NOT NULL AND doc_date IS NOT NULL")[0][0] >= 18


def test_junk_and_donations(indexed):
    groups = {r[0]: r[1] for r in q("SELECT grp, COUNT(*) FROM msg_junk GROUP BY grp")}
    assert groups.get("bounce") and groups.get("newsletter") and groups.get("paypal_spende")
    assert q("SELECT COUNT(*) FROM msg_junk j JOIN messages m ON m.id = j.id WHERE m.subject LIKE 'AW:%' AND j.grp IN ('newsletter','shop','system')")[0][0] == 0
    d = q("SELECT COUNT(*), COUNT(cents), SUM(cents) FROM donations")[0]
    assert d[0] > 0 and d[0] == d[1] and d[2] % 100 == 0
    assert q("SELECT COUNT(*) FROM donations WHERE cents IS NULL")[0][0] == 0


def test_people_levels(indexed):
    lv1 = q("SELECT name FROM people WHERE level = 1 ORDER BY name")
    assert [r[0] for r in lv1] == ["Anna Beispiel", "Bernd Muster"]
    assert q("SELECT COUNT(*) FROM people WHERE level = 2")[0][0] >= 1
    # Außenstehende werden nie einzeln gespeichert
    assert q("SELECT COUNT(*) FROM people WHERE addr LIKE '%@gmx.de' OR addr LIKE '%@t-online.de'")[0][0] == 0
    assert q("SELECT COUNT(*) FROM domain_stats WHERE kind = 'Privatmail'")[0][0] >= 1


def test_cancel(desk):
    ev = threading.Event()
    ev.set()
    job = jobs.Job(step="mails", cancel_event=ev)
    with pytest.raises(jobs.Cancelled):
        jobs.STEPS["mails"].run(jobs.Ctx(job))


def test_robust_parser(monkeypatch):
    raw = (b"From: =?UTF-8?Q?M=C3=BCller?= <m@x.org>\r\nTo: undisclosed: a@x.org, b@x.org;\r\nSubject: =?UTF-8?Q?T=C3=A4st?=\r\n"
           b"Date: Mon, 1 Jan 2024 10:00:00 +0000\r\nMessage-ID: <1@x>\r\nContent-Type: text/plain; charset=nonsense-9\r\n\r\nHallo Welt\r\n")
    m = importer.extract_lenient(raw)
    assert m["subject"] == "Täst" and m["from_name"] == "Müller" and "Hallo" in m["body_text"]

    def boom(msg):
        raise ValueError("kaputt")
    monkeypatch.setattr(importer, "extract", boom)
    from email import policy
    from email.parser import BytesParser
    assert importer.parse_any(BytesParser(policy=policy.default), raw)["subject"] == "Täst"      # Fallback greift
