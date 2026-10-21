# Der hexane-Datensatz: Aufbau und Erfahrungen

Zusammengetragen beim Bau des Programms. Alle Zahlen stammen aus dem vollständigen Datensatz (Stand der Veröffentlichung: Oktober 2026).

## Aufbau

| Teil | Inhalt | Umfang |
|---|---|---|
| `01_EMAIL/<postfach>/part-NN.mbox` | Mails als Standard-mbox, 58 Dateien, etwa zehn große Postfächer plus Reste und `unknown` | 421.179 Mails, 210 GiB |
| `03_DOCUMENTS` | PDFs, Office- und Textdateien, Namen `<index>_<sha256>.<ext>` (**keine Originalnamen**) | 48.724 Dateien, 26 GiB |
| `04_TABULAR_DATA` | WordPress-Tabellen der Parteiwebsites (`*.jsonl`) und Auswertungs-Tabellen der Veröffentlicher (`*_QUEUE.tsv`, `*_VERDICTS.tsv`) | 29 GiB |
| `02_DATABASES`, `06_MEDIA` | SQL-Dumps, Bilder aus Mailanhängen | 5,6 / 10 GiB |
| `05_CREDENTIALS_AND_KEYS` | Zugangsdaten und Schlüssel | 576 MiB (wird **nicht** ausgewertet) |
| `99_FOR_JOURNALISTS`, `_root` | Datenwörterbuch, Suchhinweise, Verifikation, `MANIFEST.tsv` | klein |

Der Datensatz wird als `.tar`-Archive verteilt. **Nach dem Entpacken sind die Ordner doppelt verschachtelt** (`01_EMAIL/01_EMAIL/…`); das Programm
löst das auf.

## Besonderheiten, die man kennen sollte

- **Entdoppelung:** Die Mails wurden nach `Message-ID` entdoppelt. Eine Mail steht nur in einem Postfach, auch wenn mehrere Personen sie bekamen.
  Die Zahl der Postfächer sagt daher wenig darüber, wessen Mails enthalten sind.
- **Mails sind überwiegend Eingang und Rauschen.** Rund 9 % sind Zustellfehler, Newsletter, Shop- und PayPal-Meldungen u. Ä. (Trash-Gruppen),
  etwa 3 % PayPal-Spendenmeldungen (12.342), 12 % Mails aus den Fanshop-Postfächern und 17 % von Absendern mit Privatmail-Adresse (meist Bürgerzuschriften).
- **Vorstandskorrespondenz liegt oft nicht auf Parteidomains**, sondern auf eigenen Domains der Beteiligten. Wer nur nach Parteidomains filtert,
  übersieht sie.
- **Die Urteile des Sprachmodells** (Schweregrad, Verhalten), die auf der Website der Veröffentlicher als „Boards" stehen, liegen **nicht** im Datensatz.
  `MAIL_QUEUE_V2.tsv` hat leere `category`/`prior_sev`. Maschinelle Felder sind laut Datenwörterbuch ohnehin keine Quellen.
- **Dokument-Metadaten** (Art, Datum, Wortzahl) gibt es nur für die Dokumente aus Mailanhängen (38.648 von 48.724), verknüpft über den `sha256` im Dateinamen.
  Die Art ist regelbasiert: `INVOICE` 9.481, `SHIPPING` 7.491, `OTHER` 3.925, `REPORT` 3.874, `LETTER` 3.510, `PRESS_MONITOR` 3.091, `FORM` 2.263, …
- **Scans:** rund 15 % der PDFs haben keine Textebene. OCR braucht für etwa 7.000 Scans mehrere Stunden bis Tage; 95 % ergaben Text.
- **Fehlerhafte Mail-Header** kommen vor (Zeilenumbrüche in Adressen, Gruppen-Adressen). Ein toleranter Parser fängt das ab; sonst gehen Mails verloren.

## Erfahrungswerte (Mittelklasse-Rechner)

- **Mail-Import:** 421.000 Mails, mehrere Stunden mit 4–6 Prozessen; Index danach etwa 5,4 GB.
- **Speicher:** Ein einzelner Tesseract-Prozess kann bei Riesenseiten (Pläne, Poster) mehrere GB belegen. Deshalb werden Seiten auf 2.600 px
  Kantenlänge begrenzt und OCR mit weniger Prozessen betrieben.
- **SQLite-Falle:** `UPDATE` schreibt die **ganze Zeile** neu. Auf einer Tabelle mit Volltexten (5 GB) dauert schon ein einfaches `UPDATE … SET x = NULL`
  Minuten bis Stunden. Deshalb stehen Zusatzdaten (Trash-Gruppen, Markierungen) in eigenen schmalen Tabellen.

## Datenschutz im Datensatz

Die Mails enthalten Namen und Adressen sehr vieler Dritter (Bürger, Bewerber, Spender, Fanshop-Kunden). Das Programm speichert deshalb für Außenstehende
keine Einzelprofile: Adressen werden nur für öffentliche Akteure (mit Quelle) und Parteidomains geführt, alle anderen nur als Zähler je Domain. Die
Spenden-Auswertung liest nur Datum und Betrag.
