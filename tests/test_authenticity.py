import base64

import pytest

from hexane_desk import authenticity as au

dkim = pytest.importorskip("dkim")
crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

MAIL = (b"From: Anna Beispiel <anna@partei-beispiel.example>\r\nTo: bernd@partei-beispiel.example\r\n"
        b"Subject: Protokoll\r\nDate: Wed, 05 Feb 2026 10:49:33 +0100\r\nMessage-ID: <abc@partei-beispiel.example>\r\n"
        b"Received: from mx.partei-beispiel.example by mail.example; Wed, 05 Feb 2026 10:49:40 +0100\r\n"
        b"Received: from pc.local by mx.partei-beispiel.example; Wed, 05 Feb 2026 10:49:34 +0100\r\n"
        b"\r\nHallo Bernd,\r\n\r\nanbei die Unterlagen.\r\n>From hier an ist es ein Zitat.\r\n")


@pytest.fixture(scope="module")
def signed():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    txt = b"v=DKIM1; k=rsa; p=" + base64.b64encode(der)
    sig = dkim.sign(MAIL, b"sel", b"partei-beispiel.example", pem, canonicalize=(b"relaxed", b"relaxed"))
    return sig + MAIL, (lambda name, timeout=5: txt)


def test_gueltige_signatur_online(signed):
    data, dns = signed
    rep = au.analyze(data, online=True, dnsfunc=dns)
    assert rep["dkim"][0]["signature"] == "valid" and rep["dkim"][0]["body_hash"] == "match"
    assert rep["verdict"] == au.OK


def test_veraenderter_text_faellt_auf(signed):
    data, dns = signed
    rep = au.analyze(data.replace(b"anbei die Unterlagen", b"anbei die GEAENDERTEN Unterlagen"), online=True, dnsfunc=dns)
    assert rep["dkim"][0]["body_hash"] == "mismatch" and rep["dkim"][0]["signature"] == "invalid"
    assert rep["verdict"] == au.BAD


def test_mbox_maskierung_und_lf_zeilenenden(signed):
    data, dns = signed
    mbox_style = data.replace(b"\r\n", b"\n").replace(b"\n>From hier", b"\n>>From hier")   # mboxrd: ein weiteres „>“
    assert au.analyze(mbox_style)["dkim"][0]["body_hash"] == "match"


def test_schluessel_fehlt(signed):
    data, _ = signed
    rep = au.analyze(data, online=True, dnsfunc=lambda name, timeout=5: None)
    assert rep["dkim"][0]["signature"] == "nokey"
    assert rep["verdict"] != au.BAD


def test_ohne_signatur_ist_kein_befund():
    rep = au.analyze(MAIL)
    assert rep["dkim"] == [] and rep["verdict"] != au.BAD
    assert any(c["id"] == "rcv_order" and c["level"] == au.OK for c in rep["checks"])


def test_received_rueckwaerts_und_datum_nach_eingang():
    bad = (b"Date: Wed, 05 Feb 2026 12:00:00 +0100\r\n"
           b"Received: from a by b; Wed, 05 Feb 2026 08:00:00 +0100\r\n"
           b"Received: from c by d; Wed, 05 Feb 2026 09:00:00 +0100\r\n\r\ntext\r\n")
    ids = {c["id"]: c["level"] for c in au.analyze(bad)["checks"]}
    assert ids["rcv_order"] == au.WARN and ids["rcv_date"] == au.WARN


def test_hash_und_bericht(signed):
    data, _ = signed
    rep = au.analyze(data, location={"file": "01_EMAIL/x/part-01.mbox", "key": "0:123"})
    assert len(rep["sha256"]) == 64
    md = au.to_markdown(rep, "Protokoll")
    assert rep["sha256"] in md and "keine Beweise" in md
