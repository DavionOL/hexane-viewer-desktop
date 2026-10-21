# hexane-viewer-desktop

Lokales Recherche-Werkzeug für Journalistinnen und Journalisten, die den **hexane-Datensatz** (Mails und Dokumente aus dem Umfeld der AfD,
rund 421.000 Mails und 48.700 Dokumente, 281 GB) vorliegen haben.

- **Volltextsuche** in Mails und Dokumenten (SQLite/FTS5), mit Suchsyntax und klickbaren **Recherche-Kategorien**
- **Bewertung** einzelner Funde (Stufe 1–5, Prüfstatus, Notiz) und **Top-100-Export** (Markdown/CSV)
- **Header-Ansicht** zur Echtheitseinschätzung von Mails (SPF/DKIM/DMARC-Angaben, Received-Kette, Hinweise)
- **Trash ausblenden**: Zustellfehler, Auto-Antworten, Newsletter, Shop-/PayPal-Meldungen, soziale Netzwerke u. a. in wählbaren Gruppen
- **Adressen mit Datensparsamkeit**: öffentliche Akteure mit Quelle, Parteidomains nur als Zähler, alle anderen nur je Domain
- **Spenden-Übersicht** aus PayPal-Meldungen ohne Namen (Anzahl, Summen, Verteilung, Spitzentage)
- **KI-Anbindung über MCP** (z. B. Claude Desktop): lesend, begrenzt, mit Maskierung
- Läuft unter **Windows, macOS und Linux**, als **Desktop-Fenster** und im **Browser**. Alles bleibt auf dem eigenen Rechner.

> **Status: frühe Entwicklung (Alpha).** Dieses Repository enthält **keine** Daten des Datensatzes, sondern nur das Programm und einen
> vollständig erfundenen Demo-Datensatz.

## Installation

**Fertiges Programm** (Windows, macOS, Linux): unter *Releases* das Archiv für das eigene System laden, entpacken, `hexane-desk` starten.
Die Programme sind nicht signiert; Windows (SmartScreen: „Weitere Informationen → Trotzdem ausführen") und macOS (Rechtsklick → „Öffnen",
oder `xattr -dr com.apple.quarantine hexane-desk`) warnen deshalb.

**Mit Python (3.11 oder neuer):**

```bash
pipx install "hexane-desk[desktop,mcp] @ git+https://github.com/DavionOL/hexane-viewer-desktop"
hexane-desk                 # Desktop-Fenster (ohne pywebview: Browser-Modus)
hexane-desk serve           # nur lokaler Server, öffnet den Browser
```

Optional installierte Programme verbessern Qualität und Tempo, sind aber nicht nötig: **Poppler** (`pdftotext`, schnellere PDF-Erkennung),
**Tesseract** mit deutschen Sprachdaten (OCR für Scans) und **catdoc** (alte `.doc`/`.xls`-Dateien).

## Erste Schritte

1. **Datensatz bereitstellen und entpacken.** Gebraucht werden etwa 281 GB für die entpackten Daten plus 6–10 GB für den Index,
   am besten auf einer SSD. Gewählt wird der Ordner, in dem `01_EMAIL`, `03_DOCUMENTS` usw. liegen.
2. **Programm starten.** Beim ersten Start öffnet sich die **Einrichtung**: Datenordner wählen („Ordner wählen …"), die Erkennung zeigt, was
   gefunden wurde.
3. **Schritte starten** („Alle empfohlenen Schritte"). Der Import von 210 GB Mails dauert je nach Rechner mehrere Stunden. Jeder Schritt
   lässt sich abbrechen und später fortsetzen. Rechner nicht in den Ruhezustand gehen lassen.
4. Danach in den Tabs **Mails**, **Dokumente**, **Adressen**, **Recherche**, **Spenden** arbeiten.

Zum Ausprobieren ohne echte Daten: `hexane-desk demo --out ./demo` erzeugt einen erfundenen Datensatz mit derselben Struktur.

## KI-Anbindung (MCP)

In der Einrichtung steht der fertige Eintrag für die Konfiguration eines KI-Clients. Siehe [docs/MCP.md](docs/MCP.md).
**Inhalte, die ein Werkzeug liefert, gehen an das Modell des verwendeten Clients.** Standardmäßig werden Adressen Außenstehender
maskiert und es gibt nur lesende Werkzeuge.

## Datenschutz und Sicherheit

- Alles läuft lokal. Der Server hört nur auf `127.0.0.1`, prüft den Hostnamen und verlangt ein Zugriffstoken; es gibt keine Telemetrie.
- Der Datensatz enthält personenbezogene Daten Dritter. Auf verschlüsselten Datenträgern arbeiten, Quellenschutz und Redaktionsregeln
  beachten. Siehe [docs/SICHERHEIT.md](docs/SICHERHEIT.md).
- Ergebnisse der Kategorien, Trash-Gruppen und Adress-Einstufung sind **Hilfen zur Orientierung, keine Belege**.

## Dokumentation

- [docs/DATENSATZ.md](docs/DATENSATZ.md): Aufbau des Datensatzes, Besonderheiten, Erfahrungswerte
- [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md): Aufbau des Programms und Entwurfsentscheidungen
- [docs/MCP.md](docs/MCP.md): KI-Anbindung
- [docs/SICHERHEIT.md](docs/SICHERHEIT.md): Bedrohungsmodell und Hinweise

## Entwicklung

```bash
pip install -e ".[dev,mcp]"
pytest                       # Tests mit erfundenem Demo-Datensatz
pip install pyinstaller && pyinstaller packaging/hexane-desk.spec   # eigenständiges Programm in dist/
```

## Lizenz

[Apache License 2.0](LICENSE). Die Referenzlisten (abgeordnetenwatch.de, FragDenStaat) werden nicht mitgeliefert, sondern nur auf Wunsch des
Nutzers geladen; deren Nutzungsbedingungen sind zu beachten. Der Datensatz selbst gehört nicht zu diesem Projekt.
