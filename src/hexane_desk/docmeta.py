"""Ergänzt die Dokumente um Metadaten der Veröffentlicher: Dokumentart, Datum, Wortzahl, Herkunft.

    (Schritt „Dokument-Metadaten“ der Einrichtung)

Verknüpfung über den sha256 im Dateinamen (`<index>_<sha256>.<ext>`):
  *_KIT_DOC_QUEUE_FULL.tsv  -> genre_det, doc_date, words
  *_DOC_QUEUE.tsv           -> source_set (Herkunft), über den sha256 im Pfad `evidence`
Die Werte sind regelbasiert (kein Sprachmodell), decken aber nur Dokumente aus Mailanhängen ab.
Andere Spalten dieser Dateien (u. a. Zähler für Bank- und Zugangsdaten) werden bewusst nicht übernommen.
Kann beliebig oft wiederholt werden.
"""
import csv
import os
import re

from . import db

SHA = re.compile(r"(?:^|[_\\/])([0-9a-f]{64})(?:\.|$)", re.I)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def num(x) -> int:
    x = (x or "").strip()
    return int(x) if x.isdigit() else 0


def find(d: str, pattern: str):
    for fn in sorted(os.listdir(d)):
        if re.fullmatch(pattern, fn):
            return os.path.join(d, fn)
    return None


def main(d: str, ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    print = ctx.log
    csv.field_size_limit(10 ** 9)
    db.init()
    conn = db.connect()

    ids: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, name FROM documents"):
        m = SHA.search(r["name"])
        if m:
            ids.setdefault(m.group(1).lower(), []).append(r["id"])
    conn.executemany("UPDATE documents SET sha256 = ? WHERE id = ?",
                     [(s, i) for s, lst in ids.items() for i in lst])
    conn.commit()
    print(f"{sum(len(v) for v in ids.values())} Dokumente mit sha256 im Namen")

    kit = find(d, r"\d+_KIT_DOC_QUEUE_FULL\.tsv")
    if kit:
        n = hit = 0
        with open(kit, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                n += 1
                lst = ids.get((row.get("sha256") or "").lower())
                if not lst:
                    continue
                date = row.get("doc_date") or ""
                vals = (row.get("genre_det") or None, date if DATE.fullmatch(date) else None, num(row.get("words")))
                for i in lst:
                    conn.execute("UPDATE documents SET genre = ?, doc_date = ?, words = ? WHERE id = ?", vals + (i,))
                    hit += 1
                if n % 5000 == 0:
                    conn.commit()
        conn.commit()
        print(f"{os.path.basename(kit)}: {n} Zeilen, {hit} Dokumente ergänzt")
    else:
        print("KIT_DOC_QUEUE_FULL nicht gefunden")

    queue = find(d, r"\d+_DOC_QUEUE\.tsv")
    if queue:
        n = hit = 0
        with open(queue, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                n += 1
                m = SHA.search(row.get("evidence") or "")
                if m and row.get("source_set"):
                    conn.execute("UPDATE documents SET source_set = ? WHERE sha256 = ?",
                                 (row["source_set"], m.group(1).lower()))
                    hit += 1
                if n % 5000 == 0:
                    conn.commit()
        conn.commit()
        print(f"{os.path.basename(queue)}: {n} Zeilen, {hit} mit Herkunft")
    conn.close()
    print("Fertig")
