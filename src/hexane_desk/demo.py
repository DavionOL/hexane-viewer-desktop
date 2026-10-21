"""Erzeugt einen kleinen, vollständig erfundenen Datensatz mit der Ordnerstruktur des echten hexane-Datensatzes.

Zum Ausprobieren und für Tests: alle Personen, Organisationen und Inhalte sind frei erfunden (Domains auf .example).

    hexane-desk demo --out ./demo-daten
"""
import hashlib
import random
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

PEOPLE = [("Anna Beispiel", "anna.beispiel@partei-beispiel.example"), ("Bernd Muster", "bernd.muster@partei-beispiel.example"),
          ("Clara Test", "clara.test@landesverband-beispiel.example"), ("Dieter Probe", "dieter@vorstand-privat.example")]
CITIZENS = ["buerger.eins@gmx.de", "petra.demo@t-online.de", "kontakt.nummer3@web.de", "zuschrift@gmail.com"]
BOXES = ["geschaeftsstelle@partei-beispiel.example", "vorstand@landesverband-beispiel.example", "fanshop@partei-beispiel.example"]
SUBJECTS = ["Sitzung des Vorstands", "Terminabstimmung", "Rechenschaftsbericht Entwurf", "Spendenquittung Vorlage",
            "Protokoll der letzten Sitzung", "Rückfrage zum Angebot", "Veranstaltung im Herbst", "Mitgliederversammlung",
            "Haushaltsplan 2019", "Anfrage der Presse"]
BODY = ("Hallo zusammen,\n\nanbei die aktuellen Unterlagen. Bitte bis Freitag prüfen und Rückmeldung geben.\n"
        "Der Rechenschaftsbericht muss vor dem Stichtag eingereicht werden.\n\nViele Grüße\n")
GENRES = ["INVOICE", "LETTER", "PROTOCOL", "CONTRACT", "SHIPPING", "PRESS_ARTICLE", "OTHER", "REPORT"]


def _msg(frm, to, subject, body, when, mid, extra=None):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = format_datetime(when)
    m["Message-ID"] = f"<{mid}@demo.example>"
    for k, v in (extra or {}).items():
        m[k] = v
    m.set_content(body)
    return m


def _mbox_bytes(messages) -> bytes:
    out = []
    for m in messages:
        data = m.as_bytes().replace(b"\r\n", b"\n")
        data = b"\n".join((b">" + ln if ln.startswith(b"From ") else ln) for ln in data.split(b"\n"))
        out.append(b"From demo@demo.example Mon Jan  1 00:00:00 2018\n" + data.rstrip(b"\n") + b"\n\n")
    return b"".join(out)


def make_pdf(lines: list[str] | None) -> bytes:
    """Kleine, gültige PDF-Datei. lines=None ergibt eine „Scan“-Seite ohne Textebene."""
    def esc(t: str) -> bytes:
        return t.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    if lines:
        stream = b"BT /F1 12 Tf 50 780 Td 16 TL " + b" ".join(b"(" + esc(l) + b") Tj T*" for l in lines) + b" ET"
    else:
        stream = b"0.8 g 50 400 300 200 re f"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def _zip(path: Path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)


def make(out: str | Path, n_mails: int = 300, seed: int = 1) -> Path:
    rnd = random.Random(seed)
    out = Path(out)
    base = datetime(2016, 1, 1, tzinfo=timezone.utc)
    mid = 0

    # ---- Mails
    per_box = max(1, n_mails // len(BOXES))
    for box in BOXES:
        d = out / "01_EMAIL" / "01_EMAIL" / box
        d.mkdir(parents=True, exist_ok=True)
        msgs = []
        for i in range(per_box):
            mid += 1
            when = base + timedelta(hours=rnd.randint(0, 24 * 365 * 4))
            kind = rnd.random()
            (fn, fa), (tn, ta) = rnd.sample(PEOPLE, 2)
            frm, to = f"{fn} <{fa}>", f"{tn} <{ta}>"
            subj = rnd.choice(SUBJECTS)
            extra = {}
            body = BODY
            if kind < 0.05:
                frm, subj, body = "MAILER-DAEMON@mx.example", "Undelivered Mail Returned to Sender", "Die Nachricht konnte nicht zugestellt werden.\n"
            elif kind < 0.08:
                subj, body = "Automatische Antwort: " + subj, "Ich bin bis Montag nicht erreichbar.\n"
            elif kind < 0.13:
                frm, subj, body = "newsletter@shop.example", "Newsletter Oktober", "Neuigkeiten. Zum Abbestellen hier klicken.\n"
            elif kind < 0.17:
                frm, subj, body = "versand@shop.example", f"Ihre Bestellung Nr. {rnd.randint(1000, 9999)} wurde versendet", "Ihr Paket ist unterwegs.\n"
            elif kind < 0.30:
                amount = rnd.choice([10, 20, 25, 50, 50, 100, 250])
                frm, subj = "service@paypal.de", "Sie haben eine Spende erhalten"
                body = f"Sie haben eine Spende in Höhe von {amount},00 € EUR erhalten. Gebühr: 1,20 EUR\n"
            elif kind < 0.34:
                frm, subj, body = "info@twitter.com", "Neue Follower", "Sie haben neue Follower.\n"
            elif kind < 0.50:
                frm, subj = rnd.choice(CITIZENS), "WG: Wichtige Information"
                body = "Bitte weiterleiten: Kettenmail mit Meinung zum Sommerfest.\n"
            elif kind < 0.60:
                extra = {"Authentication-Results": "mx.example; spf=pass; dkim=pass header.d=partei-beispiel.example; dmarc=pass",
                         "DKIM-Signature": "v=1; a=rsa-sha256; d=partei-beispiel.example; s=sel1; c=relaxed/relaxed; h=from:to; bh=a; b=b"}
            if rnd.random() < 0.3 and kind >= 0.34:
                subj = "AW: " + subj
            msgs.append(_msg(frm, to, subj, body, when, mid, extra))
        (d / "part-01.mbox").write_bytes(_mbox_bytes(msgs))

    # ---- Dokumente (Namen wie im echten Datensatz: <index>_<sha256>.<ext>) und Queue-Tabellen
    docs = out / "03_DOCUMENTS" / "03_DOCUMENTS"
    docs.mkdir(parents=True, exist_ok=True)
    tab = out / "04_TABULAR_DATA" / "04_TABULAR_DATA"
    tab.mkdir(parents=True, exist_ok=True)
    kit = ["uid\tsha256\text\tchars\twords\tdoc_date\tgenre_det\tis_tabular\tis_roster\tn_iban\tn_email\tn_phone\tn_address\tn_money\tn_secrets\ttext"]
    queue = ["uid\tsource_set\tcategory\tprior_sev\tactor\tidentity_link\tevidence\ttext\tunresolved"]
    texts = ["Rechnung Nr. 4711 für Druckkosten Wahlkampfmaterial", "Protokoll der Vorstandssitzung: Haushalt und Spendenquittungen",
             "Sehr geehrte Frau Beispiel, hiermit bestätigen wir den Eingang Ihrer Barspende", "Vertrag über Raummiete für die Mitgliederversammlung",
             "Pressespiegel Oktober: Artikel über die Landesverband-Konferenz", "Lieferschein Paket Fanshop Artikel"]
    for i, t in enumerate(texts):
        for ext in ("docx", "txt", "pdf"):
            if ext == "docx":
                data = None
                tmp = docs / "tmp.docx"
                _zip(tmp, {"word/document.xml": f"<w:document><w:body><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:body></w:document>"})
                data = tmp.read_bytes()
                tmp.unlink()
            elif ext == "txt":
                data = (t + "\n").encode()
            else:
                data = make_pdf([t, "Erfundenes Demo-Dokument."])
            sha = hashlib.sha256(data + str(i).encode()).hexdigest()
            name = f"{len(kit):06d}_{sha}.{ext}"
            (docs / name).write_bytes(data)
            genre = GENRES[(i + len(ext)) % len(GENRES)]
            date = f"{2016 + (i % 4)}-0{1 + i % 9}-1{i % 9}"
            kit.append(f"doc-{sha[:16]}\t{sha}\t{ext}\t{len(t)}\t{len(t.split())}\t{date}\t{genre}\t0\t0\t0\t0\t0\t0\t0\t0\t{t}")
            queue.append(f"doc-{sha[:16]}\tpartei-beispiel.example\t\t\t\t\tn2_attachments\\{sha[:2]}\\{sha}.{ext}\t{t}\t0")
    scan = make_pdf(None)
    sha = hashlib.sha256(scan).hexdigest()
    (docs / f"{len(kit):06d}_{sha}.pdf").write_bytes(scan)          # „Scan“ ohne Textebene
    (tab / "000042_KIT_DOC_QUEUE_FULL.tsv").write_text("\n".join(kit) + "\n", encoding="utf-8")
    (tab / "000010_DOC_QUEUE.tsv").write_text("\n".join(queue) + "\n", encoding="utf-8")

    # ---- Begleitdateien
    j = out / "99_FOR_JOURNALISTS" / "99_FOR_JOURNALISTS"
    j.mkdir(parents=True, exist_ok=True)
    (j / "README_FOR_JOURNALISTS.md").write_text("# Demo-Datensatz\n\nAlles hier ist erfunden und dient nur dem Ausprobieren des Programms.\n", encoding="utf-8")
    r = out / "_root"
    r.mkdir(exist_ok=True)
    (r / "README.md").write_text("Erfundener Demo-Datensatz (hexane-desk demo).\n", encoding="utf-8")
    (r / "MANIFEST.tsv").write_text("path\tsize\nDemo\t0\n", encoding="utf-8")
    return out
