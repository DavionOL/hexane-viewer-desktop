"""Recherche-Kategorien für die klickbaren Filter im Viewer.

Die Begriffe sind Suchhinweise, keine Belege: Ein Treffer sagt nur, wo man lesen sollte. Immer Richtung (wer schreibt an wen),
Verlauf und Kontext prüfen. Einzelne Wörter werden als Wortanfang gesucht ("remigr" findet "Remigration"), Einträge mit
Leerzeichen als Phrase. Die Liste ist bewusst eine Datei im Projekt und kann jederzeit angepasst werden.
"""

CATEGORIES = [
    {"key": "menschenwuerde", "label": "A  Rassismus / Menschenwürde",
     "desc": "Rassistische, menschenverachtende oder volksverhetzende Sprache (Menschenwürde, §130 StGB)",
     "terms": ["remigr", "umvolk", "bevölkerungsaustausch", "großer austausch", "ethnopluralis", "passdeutsch",
               "volkstod", "überfremd", "ausländerfrei", "neger", "zigeuner", "kanake", "gesindel", "artfremd",
               "rassenschande", "untermensch", "schmarotzer", "invasoren", "vergasen", "blut und boden",
               "sieg heil", "heil hitler"]},
    {"key": "extremismus", "label": "B  Verbindungen zum Rechtsextremismus",
     "desc": "Kontakte zu extremistischen Organisationen, Unvereinbarkeit, Ausschlussverfahren",
     "terms": ["identitäre", "reconquista", "dritter weg", "iii. weg", "npd", "die heimat", "ein prozent",
               "reichsbürger", "kameradschaft", "rechtsrock", "neonazi", "holocaustleugn", "skinhead",
               "hammerskin", "combat 18", "blood and honour", "autonome nationalisten", "unvereinbarkeit",
               "ausschlussverfahren", "parteiausschluss"]},
    {"key": "demokratie", "label": "C  Demokratie- und Rechtsstaatsfeindlichkeit",
     "desc": "Umsturz, Delegitimierung von Staat, Presse und Justiz, Gewaltfantasien gegen das System",
     "terms": ["systemparteien", "volksverräter", "lügenpresse", "umsturz", "staatsstreich", "tag x",
               "widerstandsrecht", "diktatur", "gleichschaltung", "verfassungsschutz abschaffen", "säubern",
               "volksgerichtshof", "gewaltenteilung"]},
    {"key": "finanzen", "label": "D  Parteienfinanzierung / Spenden",
     "desc": "Verschleierte oder unzulässige Spenden, falsche Rechenschaftsberichte (Parteiengesetz)",
     "terms": ["barspende", "stückelung", "strohmann", "spendenquittung", "zuwendungsbescheinigung",
               "rechenschaftsbericht", "schwarzgeld", "ohne rechnung", "bargeld", "umschlag", "schweiz",
               "spender", "bundestagsverwaltung", "strafzahlung", "parteiengesetz", "scheinrechnung",
               "rückdatier", "nachträglich ausgestellt", "kassenprüfer"]},
    {"key": "veruntreuung", "label": "E  Veruntreuung / Amtsmissbrauch",
     "desc": "Scheinarbeitsverhältnisse, Fraktionsgelder, Vetternwirtschaft, Interessenkonflikte",
     "terms": ["scheinarbeit", "scheinvertrag", "scheinanstellung", "fraktionsgeld", "abgeordnetenbezüge",
               "mitarbeiterpauschale", "beratervertrag", "vetternwirtschaft", "nepotismus", "interessenkonflikt",
               "untreue", "veruntreu", "unterschlag", "fiktive"]},
    {"key": "einfluss", "label": "F  Einflussnahme / Korruption",
     "desc": "Zuwendungen und Kontakte zu fremden Staaten, Lobbyisten und Unternehmen",
     "terms": ["russland", "moskau", "kreml", "putin", "china", "peking", "voice of europe", "gastgeschenk",
               "honorar", "sponsoring", "lobby", "bestechung", "schmiergeld", "provision"]},
    {"key": "daten", "label": "G  Datenschutz / Zugangsdaten",
     "desc": "Weitergabe von Mitglieder- und Spenderdaten, Passwörter, Datenpannen",
     "terms": ["mitgliederliste", "mitgliederdaten", "spenderliste", "passwort", "zugangsdaten", "datenleck",
               "datenschutz", "datenpanne", "verteiler offen", "hacker"]},
    {"key": "drohung", "label": "H  Drohung / Einschüchterung",
     "desc": "Drohungen, Prangerlisten, Gewaltandeutungen. Absender prüfen: Partei oder Außenstehende?",
     "terms": ["drohung", "prangerliste", "feindesliste", "feindeliste", "antifa", "anschlag", "bewaffn",
               "erschießen", "aufhängen", "selbstjustiz", "einschüchter", "denunzier", "meldeportal"]},
]

BY_KEY = {c["key"]: c for c in CATEGORIES}

SEVERITY_LABELS = {1: "auffällig", 2: "bedenklich", 3: "gravierend", 4: "schwerwiegend", 5: "kritisch"}
VERIFIED_LABELS = {0: "ungeprüft", 1: "Echtheit geprüft", 2: "Echtheit und Kontext geprüft"}
