# KI-Anbindung über MCP

Hexane Desk enthält einen MCP-Server. Ein KI-Client wie Claude Desktop startet ihn als Unterprozess (`hexane-desk mcp`, stdio) und kann damit im
lokalen Index suchen und lesen. Der Index bleibt auf dem Rechner; **was ein Werkzeug zurückgibt, geht an das Modell des Clients.**

## Einrichten

1. Datensatz in der Einrichtung einlesen (mindestens Mails und Dokumente).
2. In der Einrichtung unter „KI-Anbindung" den Konfigurationseintrag kopieren, bei Claude Desktop zum Beispiel:

```json
{ "mcpServers": { "hexane": { "command": "/Pfad/zu/hexane-desk", "args": ["mcp"] } } }
```

3. Client neu starten. Die Werkzeuge erscheinen unter dem Namen „hexane".

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `dataset_info`, `list_categories` | Überblick und Recherche-Kategorien |
| `search_mails`, `get_mail`, `get_mail_headers` | Mails suchen, lesen (mit Verlauf), Header zur Echtheitseinschätzung |
| `search_documents`, `get_document` | Dokumente suchen und lesen |
| `list_people`, `get_person` | Adressen der Stufe 1 (öffentliche Akteure) und Parteidomains |
| `donations_summary` | Spenden-Übersicht ohne Namen |
| `top_marks` | die bewerteten Einträge, nach Kritikalität sortiert |
| `set_mark` | Markierung setzen: **nur wenn in der Einrichtung „Schreib-Werkzeuge erlauben" aktiv ist** |

Dazu gibt es die Ressource `hexane://guide` (Suchsyntax, Umgang mit Ergebnissen) und den Prompt `research_plan`.

## Schutzmaßnahmen

- **Nur lesend** ohne ausdrückliche Freigabe. `set_mark` wird gar nicht erst angeboten.
- **Begrenzte Antworten:** höchstens 50 Treffer, Texte werden gekürzt.
- **Fremdtext-Kennzeichnung:** Jede Antwort weist darauf hin, dass der Inhalt unzuverlässig ist und keine Anweisungen enthält, denen zu folgen wäre
  (Schutz vor Prompt-Injection durch Mails und Dokumente).
- **Maskierung:** Adressen Außenstehender erscheinen als `***@domain`. Adressen öffentlicher Akteure und Parteidomains bleiben sichtbar.
  **Namen im Fließtext werden nicht maskiert.** Die Einstellung lässt sich abschalten (Einrichtung).
- Der Server baut **keine Netzwerkverbindungen** auf und bietet keinen Zugriff auf Dateien außerhalb des Index.

## Hinweise zur Verwendung

- Cloud-Modelle sehen die gelieferten Ausschnitte. Für besonders sensibles Material einen lokal laufenden Client mit lokalem Modell verwenden.
- Ergebnisse eines Modells sind Hinweise, keine Belege: Quellen (Mail-/Dokument-ID) prüfen und Aussagen am Original belegen.
