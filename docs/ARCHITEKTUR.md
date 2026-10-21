# Architektur

```
 Desktop-Fenster (pywebview)      Browser
            \                      /
             \                    /
        FastAPI-Server (127.0.0.1, Zugriffstoken)   ──  statische Oberfläche (static/index.html)
                  |
       Kern: Importer · Dokumente · Auswertungen · Markierungen
                  |
        SQLite + FTS5 (index.sqlite im Benutzerprofil)        MCP-Server (stdio) ── liest denselben Index
                  |
        Datensatz (nur lesend, beliebiger Ordner)
```

## Bausteine (`src/hexane_desk/`)

| Modul | Aufgabe |
|---|---|
| `config.py` | Einstellungen und Pfade (Windows/macOS/Linux über `platformdirs`; `HEXANE_DESK_HOME` für Tests/portablen Betrieb), Zugriffstoken |
| `datasets.py` | erkennt die Teile des Datensatzes im gewählten Ordner (auch doppelt verschachtelt), Hilfsprogramme |
| `jobs.py` | Einrichtungsschritte als Hintergrund-Jobs mit Fortschritt, Abbruch und gemerktem Stand |
| `importer.py` | mbox/eml/Maildir → Index; Byte-Offsets je Mail, toleranter Fallback-Parser, parallele Arbeitsprozesse |
| `docs.py`, `docmeta.py` | Dokumenttexte (pdftotext oder pypdf, Zip-XML, optional catdoc/Tesseract); Metadaten aus den Queue-Tabellen |
| `people.py`, `lists.py` | Adress-Einstufung in Stufen; Referenzlisten (nur auf Wunsch aus dem Internet) |
| `junk.py`, `donations.py`, `categories.py` | Trash-Gruppen, Spenden-Übersicht (ohne Namen), Recherche-Kategorien |
| `server.py` | HTTP-Schnittstelle und Zugriffsschutz |
| `mcp_server.py` | KI-Anbindung |
| `demo.py` | erfundener Demo-Datensatz für Tests und zum Ausprobieren |
| `cli.py` | `desktop`, `serve`, `index`, `demo`, `doctor`, `mcp` |

## Entwurfsentscheidungen

- **Eine Codebasis für Desktop und Browser:** Die Oberfläche ist eine lokale Webseite; das Desktop-Fenster zeigt sie nur an und bietet den Ordnerdialog des Systems.
- **Index im Benutzerprofil, Datensatz unverändert:** Alle Pfade im Index sind relativ zum gewählten Datenordner; Originale werden nur gelesen.
- **Schritte statt Skripte:** Jeder Schritt ist wiederholbar und setzt fort (z. B. `import_done`, `documents.path`).
- **Mehrprozess mit `spawn`:** gleiches Verhalten unter Windows, macOS und Linux; gepackte Programme brauchen `freeze_support()` im Einstiegspunkt.
- **Schmale Tabellen für Zusatzdaten** (`msg_junk`, `marks`, `donations`): kein `UPDATE` auf den großen Zeilen von `messages`.
- **Markierungen hängen an Quelldatei + mbox-Schlüssel**, nicht an der internen ID: Sie überleben einen Neuaufbau des Index.
- **Datensparsamkeit als Standard:** Einzeladressen nur für öffentliche Akteure und Parteidomains; Spenden ohne Namen; MCP maskiert Außenstehende.
- **Optionale Hilfsprogramme:** Es läuft ohne Poppler/Tesseract/catdoc (eingebaute Verfahren); sind sie vorhanden, werden sie genutzt.

## Datenmodell (SQLite)

`messages` (+`messages_fts`), `attachments`, `documents` (+`documents_fts`), `import_done`, `steps`, `marks`, `msg_junk`, `people`, `pairs`,
`domain_stats`, `donations`. Das Schema steht in `db.py`; Änderungen kommen über `db.migrate()`.
