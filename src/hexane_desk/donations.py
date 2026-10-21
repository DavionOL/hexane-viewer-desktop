"""Spenden-Übersicht ohne Namen: liest aus den PayPal-Spendenmeldungen nur Datum und Betrag.

    (Schritt „Spenden-Übersicht“ der Einrichtung)

Es werden weder Namen noch Adressen oder Textteile gespeichert, nur (Mail-ID, Datum, Betrag in Cent). Der Betrag wird
bevorzugt nach Stichwörtern („Spende von/über …“, „Betrag“, „Summe“) gesucht, sonst der erste Betrag im Text.
Das Skript meldet, wie viele Meldungen lesbar waren; bei niedriger Quote muss die Erkennung angepasst werden.
Kann beliebig oft wiederholt werden (die Tabelle wird neu aufgebaut).
"""
import re
from collections import Counter

from . import db

TS_MIN, TS_MAX = 631152000, 2051222400
CUR = r"(?:€|EUR|Euro)"
AMOUNT = re.compile(rf"(?:{CUR}\s*(?P<a>\d[\d.,  ]*\d|\d)|(?P<b>\d[\d.,  ]*\d|\d)\s*{CUR})", re.I)
KEYWORD = re.compile(r"(?:spende\s+(?:in\s+höhe\s+)?(?:von|über)|in\s+höhe\s+von|bruttobetrag|gesamtbetrag|betrag|summe)", re.I)
MAX_CENTS = 10_000_000        # 100.000 €: alles darüber gilt als Fehlerkennung


def to_cents(s: str):
    s = s.replace(" ", "").replace(" ", "")
    if not re.fullmatch(r"\d[\d.,]*", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        dec = "," if re.search(r",\d{1,2}$", s) else None
    elif "." in s:
        dec = "." if re.search(r"\.\d{1,2}$", s) and s.count(".") == 1 else None
    else:
        dec = None
    if dec:
        ip, _, fp = s.rpartition(dec)
        ip, fp = re.sub(r"[.,]", "", ip), (fp + "00")[:2]
    else:
        ip, fp = re.sub(r"[.,]", "", s), "00"
    try:
        c = int(ip) * 100 + int(fp)
    except ValueError:
        return None
    return c if 0 < c <= MAX_CENTS else None


def first_amount(text: str):
    for m in AMOUNT.finditer(text):
        c = to_cents(m.group("a") or m.group("b"))
        if c:
            return c
    return None


def extract_amount(body: str):
    """(Cent, Methode) – Methode 'kw' (nach Stichwort), 'first' (erster Betrag) oder ('None', 'none')."""
    body = (body or "")[:6000]
    for k in KEYWORD.finditer(body):
        c = first_amount(body[k.end(): k.end() + 90])
        if c:
            return c, "kw"
    c = first_amount(body)
    return (c, "first") if c else (None, "none")


def main(ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    print = ctx.log
    db.init()
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, date_ts, substr(body_text, 1, 6000) AS body FROM messages "
        "WHERE from_addr LIKE '%@paypal.%' AND subject LIKE '%spende%' "
        "AND subject NOT LIKE 're:%' AND subject NOT LIKE 'aw:%'").fetchall()
    conn.execute("DELETE FROM donations")
    how = Counter()
    out = []
    for r in rows:
        cents, h = extract_amount(r["body"])
        how[h] += 1
        ts = r["date_ts"] if r["date_ts"] and TS_MIN <= r["date_ts"] <= TS_MAX else None
        out.append((r["id"], ts, cents, h))
    conn.executemany("INSERT INTO donations (msg_id, ts, cents, how) VALUES (?,?,?,?)", out)
    conn.commit()
    n = len(rows)
    print(f"{n} Spendenmeldungen")
    print(f"  Betrag nach Stichwort gefunden : {how['kw']:>7d}  ({100 * how['kw'] / max(n, 1):.1f} %)")
    print(f"  erster Betrag im Text          : {how['first']:>7d}  ({100 * how['first'] / max(n, 1):.1f} %)")
    print(f"  nicht lesbar                   : {how['none']:>7d}  ({100 * how['none'] / max(n, 1):.1f} %)")
    s = conn.execute("SELECT COUNT(*), SUM(cents), MIN(cents), MAX(cents) FROM donations WHERE cents IS NOT NULL").fetchone()
    if s[0]:
        print(f"  gelesene Beträge: {s[0]}, Summe {s[1] / 100:,.2f} €, kleinster {s[2] / 100:.2f} €, größter {s[3] / 100:.2f} €")
    conn.close()
