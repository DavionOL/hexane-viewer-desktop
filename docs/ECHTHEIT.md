# Echtheitsprüfung von Mails

Der Knopf **Echtheit** an jeder Mail erstellt einen Bericht. Er liefert **Indizien, keine Beweise**. Ein Bericht kann „Indizien sprechen für Echtheit"
lauten oder Auffälligkeiten nennen; ein belastbares Urteil ersetzt er nicht. Echt heißt nur: so verschickt, nicht: inhaltlich wahr.

## Was geprüft wird

| Prüfung | Aussage | Grenzen |
|---|---|---|
| **DKIM, Hash** (offline) | Der Text passt zum Hash in der Signatur | Ohne Schlüssel kann ein Fälscher Hash und Signatur neu schreiben: nur Hinweis |
| **DKIM, Signatur** (online, mit Zustimmung) | Der Server der Absender-Domain hat Text und signierte Header so signiert; seitdem unverändert | Der Schlüssel muss noch im DNS stehen; Exportveränderungen (Zeilenenden, Listen-Zusätze im Betreff) können eine echte Signatur brechen |
| **Authentication-Results** | Was der Empfangsserver damals eingetragen hat (spf/dkim/dmarc) | Nur so vertrauenswürdig wie der Server; Fälschungen können eigene Zeilen mitbringen |
| **Zustellweg** | Zeitstempel der Received-Zeilen steigen; Datum der Mail passt zum Eingang | Uhrenabweichungen kommen vor, Fälscher können die Zeilen sorgfältig bauen |
| **Verweise** | Mail, auf die geantwortet wird, und weitere Mails des Verlaufs sind im Datensatz | Der Datensatz ist entdoppelt und nicht vollständig |
| **Anhänge** | SHA-256, Erstellprogramm und Erstelldatum bei PDF/Office; Warnung, wenn nach der Mail erstellt | Metadaten lassen sich ändern oder fehlen |
| **Hash der Roh-Mail, Fundort** | Macht die Prüfung reproduzierbar und dokumentierbar | Beweist keine Echtheit, nur Identität der Datei |

Ohne DKIM-Signatur gibt es **keinen** Befund: viele Mails sind nie signiert worden.

## Datenschutz

Die Online-Prüfung ist **aus**, bis sie ausdrücklich erlaubt wird (Einrichtung oder Rückfrage im Bericht). Dann geht je Prüfung nur
`selector._domainkey.domain` als DNS-Anfrage ins Internet, kein Text und keine Adresse. Anhang-Metadaten zeigen kein Autorenfeld.

## Echtheits-Statistik

Der optionale Schritt **Echtheits-Statistik** liest alle Mails noch einmal und zählt je Postfach, wie viele eine Signatur tragen, bei wie vielen der
Hash passt und was die Empfangsserver eingetragen haben. Gespeichert werden nur Zähler, kein Text. Wo viele Mails signiert sind, ist die Herkunft
besser belegbar; die Zahlen sagen nichts über den Wahrheitsgehalt.

## Bericht für die Dokumentation

„Bericht als Markdown" speichert Ergebnisse, Hash, Fundort (Datei, Offset, Länge) und die Prüfsummen der Anhänge. Wer denselben Datensatz hat,
kann die Mail damit wiederfinden und das Ergebnis nachvollziehen.

## Was fehlt

Abgleich mit der `MANIFEST.tsv` des Datensatzes (Integrität des Downloads), Vergleich zitierter Mailtexte mit dem Original, Prüfung von Fotos (EXIF).
