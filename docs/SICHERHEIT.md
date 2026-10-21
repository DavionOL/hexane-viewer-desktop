# Sicherheit und Datenschutz

## Bedrohungsmodell

Das Programm verarbeitet einen Datensatz mit sehr vielen personenbezogenen Daten Dritter. Es soll verhindern, dass diese Daten versehentlich
abfließen oder von anderen Programmen und Webseiten auf demselben Rechner gelesen werden.

| Risiko | Gegenmaßnahme |
|---|---|
| Andere Webseiten im Browser lesen den lokalen Server aus (DNS-Rebinding, CSRF) | Nur Hostnamen `127.0.0.1`/`localhost`; Zugriff nur mit Token-Cookie (`SameSite=Strict`), das der Link aus dem Programm setzt |
| Server im Netzwerk erreichbar | Standard: nur `127.0.0.1`; Netzwerk-Modus nur mit `--lan` **und** Passwort, Ordnerauswahl dort abgeschaltet |
| Bösartige Inhalte in Mails (HTML, Skripte) | HTML-Mails im `sandbox`-Iframe mit strenger Content-Security-Policy; Anhänge nur als Download |
| Pfade außerhalb des Datenordners | Alle Dateizugriffe werden gegen den Datenordner geprüft |
| Prompt-Injection über die KI-Anbindung | Antworten als Fremdtext gekennzeichnet, nur lesende Werkzeuge standardmäßig, begrenzte Länge |
| Profilbildung über Außenstehende | Keine Einzelprofile: nur Zähler je Domain; Spenden ohne Namen; Maskierung im MCP |
| Datenabfluss durch das Programm | Keine Telemetrie. Netzzugriff nur für das ausdrücklich erlaubte Laden der Referenzlisten |

## Was das Programm nicht leistet

- Es **verschlüsselt den Index nicht**. Der Index enthält Mailtexte. Auf einem verschlüsselten Datenträger arbeiten.
- Die **Echtheitsprüfung** der Mails ist eine Einschätzung anhand der Header, keine kryptografische Prüfung.
- Kategorien, Trash-Gruppen und die Einstufung von Adressen sind **heuristisch**. Namensvettern, falsche Treffer und übersehene Fälle sind möglich.

## Hinweise für die Arbeit (keine Rechtsberatung)

- Quellenschutz und Redaktionsregeln gelten auch für den Umgang mit dem Datensatz; Rechercheergebnisse nicht ungeschützt teilen.
- Vor einer Veröffentlichung: Verdachtsberichterstattung (belegter Mindestbestand, Anhörung), Schutz Unbeteiligter, Rechtsprüfung.
- Die Parteizugehörigkeit ist ein besonders geschütztes Datum. Das Programm leitet sie nie aus Mailinhalten ab; sie wird nur für Personen
  angezeigt, die in öffentlichen Listen mit Quelle geführt sind.
- Die Referenzlisten stammen von abgeordnetenwatch.de und FragDenStaat. Deren Nutzungsbedingungen beachten.

## Schwachstellen melden

Bitte nicht öffentlich als Issue, sondern über die Sicherheitsfunktion des GitHub-Repositories („Report a vulnerability").
