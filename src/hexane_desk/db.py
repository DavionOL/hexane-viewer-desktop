import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    folder      TEXT NOT NULL,          -- z.B. "Postfach/Inbox"
    source_path TEXT NOT NULL,          -- Datei im Rohdaten-Verzeichnis (relativ)
    mbox_key    TEXT,                   -- nur bei mbox-Dateien
    message_id  TEXT,
    thread_id   TEXT,
    from_name   TEXT,
    from_addr   TEXT,
    to_addrs    TEXT,
    cc_addrs    TEXT,
    subject     TEXT,
    date_ts     INTEGER,                -- Unix-Zeit (UTC)
    preview     TEXT,
    body_text   TEXT,
    has_html    INTEGER DEFAULT 0,
    att_count   INTEGER DEFAULT 0,
    size        INTEGER DEFAULT 0,
    UNIQUE (source_path, mbox_key)
);
CREATE INDEX IF NOT EXISTS idx_msg_folder_date ON messages (folder, date_ts DESC);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages (thread_id);
CREATE INDEX IF NOT EXISTS idx_msg_date ON messages (date_ts DESC);

CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY,
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    part_index   INTEGER NOT NULL,
    filename     TEXT,
    content_type TEXT,
    size         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_att_msg ON attachments (message_id);

-- vollständig importierte Dateien (für Fortsetzen nach Abbruch)
CREATE TABLE IF NOT EXISTS import_done (
    source_path TEXT PRIMARY KEY
);

-- Volltextindex; rowid = messages.id
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject, from_text, to_text, body,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Dokumente (03_DOCUMENTS): extrahierter Text, Volltextindex mit rowid = documents.id
CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,    -- relativ zum Rohdaten-Verzeichnis
    name       TEXT NOT NULL,
    ext        TEXT NOT NULL,
    size       INTEGER DEFAULT 0,
    mtime      INTEGER,
    pages      INTEGER DEFAULT 0,
    preview    TEXT,
    text       TEXT,
    ocr_status INTEGER DEFAULT 0        -- 0 kein OCR nötig, 1 Scan ohne Text, 2 OCR erledigt, 3 OCR ohne Ergebnis
);
CREATE INDEX IF NOT EXISTS idx_doc_ext ON documents (ext);
CREATE INDEX IF NOT EXISTS idx_doc_ocr ON documents (ocr_status);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    name, body,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Adressen-Auswertung (app/people.py). Einzeladressen nur für öffentliche Akteure (Stufe 1) und Parteidomains (Stufe 2);
-- alle anderen werden nur je Domain gezählt.
CREATE TABLE IF NOT EXISTS people (
    addr     TEXT PRIMARY KEY,          -- kleingeschrieben
    name     TEXT,
    domain   TEXT,
    level    INTEGER NOT NULL,          -- 1 Amtsträger / öffentliche Person, 2 Parteidomain (Funktion unklar)
    source   TEXT,                      -- Quelle der Einstufung
    n_sent   INTEGER DEFAULT 0,
    n_recv   INTEGER DEFAULT 0,         -- als An/Cc
    first_ts INTEGER,
    last_ts  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_people_level ON people (level);
CREATE TABLE IF NOT EXISTS pairs (
    src TEXT NOT NULL,                  -- Adresse (Stufe 1/2) oder "@domain"
    dst TEXT NOT NULL,
    n   INTEGER NOT NULL,
    PRIMARY KEY (src, dst)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_pairs_dst ON pairs (dst);
CREATE TABLE IF NOT EXISTS domain_stats (
    domain  TEXT PRIMARY KEY,
    kind    TEXT,                       -- Behörde/Parlament, Privatmail, Sonstige
    n_addrs INTEGER,
    n_sent  INTEGER,
    n_recv  INTEGER
);

-- Trash-Gruppe je Mail (app/junk.py). Bewusst eine eigene schmale Tabelle: ein UPDATE auf messages würde
-- die ganzen Zeilen samt Volltext neu schreiben.
CREATE TABLE IF NOT EXISTS msg_junk (
    id  INTEGER PRIMARY KEY,            -- messages.id
    grp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_junk_grp ON msg_junk (grp);

-- Stand der Einrichtungsschritte (siehe jobs.py)
CREATE TABLE IF NOT EXISTS steps (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL,          -- done | failed | cancelled
    finished_ts INTEGER,
    info        TEXT
);

-- Echtheits-Statistik (authstats.py): nur Zähler und Prüfergebnisse je Mail, kein Text
CREATE TABLE IF NOT EXISTS auth_stats (
    msg_id  INTEGER PRIMARY KEY,
    sigs    INTEGER DEFAULT 0,          -- Anzahl DKIM-Signaturen
    bh_ok   INTEGER DEFAULT 0,          -- davon: Hash passt zum Text
    ar_dkim TEXT, ar_spf TEXT, ar_dmarc TEXT,   -- Ergebnis laut Authentication-Results des Empfangsservers
    skipped INTEGER DEFAULT 0           -- zu groß oder nicht lesbar
);

-- Spenden-Übersicht (app/donations.py): nur Datum und Betrag aus PayPal-Spendenmeldungen. Bewusst KEINE Namen,
-- Adressen oder Texte; die Mail-ID dient nur der Entdoppelung.
CREATE TABLE IF NOT EXISTS donations (
    msg_id INTEGER PRIMARY KEY,
    ts     INTEGER,                     -- Datum der Meldung (Unix-Zeit), NULL bei kaputtem Datum
    cents  INTEGER,                     -- Betrag in Cent, NULL wenn nicht lesbar
    how    TEXT                         -- 'kw' (Betrag nach Stichwort), 'first' (erster Betrag im Text), 'none'
);

-- Recherche: manuelle Bewertungen. Verweist über Quelldatei (+ mbox-Schlüssel) statt über die interne id,
-- damit Markierungen einen Neuaufbau des Index überleben.
CREATE TABLE IF NOT EXISTS marks (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,           -- 'mail' | 'doc'
    src        TEXT NOT NULL,           -- source_path (Mail) bzw. path (Dokument)
    key        TEXT NOT NULL DEFAULT '',-- mbox_key, bei Dokumenten leer
    title      TEXT,                    -- Titel zum Zeitpunkt der Bewertung (Betreff / Dokumenttitel)
    subtitle   TEXT,                    -- Absender und Datum bzw. Dateiname
    severity   INTEGER NOT NULL,        -- 1 auffällig .. 5 kritisch
    category   TEXT,                    -- Schlüssel aus app/categories.py
    note       TEXT,
    verified   INTEGER NOT NULL DEFAULT 0,  -- 0 ungeprüft, 1 Echtheit geprüft, 2 Echtheit und Kontext geprüft
    created_ts INTEGER,
    updated_ts INTEGER,
    UNIQUE (kind, src, key)
);
CREATE INDEX IF NOT EXISTS idx_marks_rank ON marks (severity DESC, verified DESC, updated_ts DESC);
"""


def connect(readonly: bool = False) -> sqlite3.Connection:
    path = config.index_path()
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False, timeout=120)
        conn.row_factory = sqlite3.Row
        return conn
    os.makedirs(path.parent, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=120)   # warten statt "database is locked"
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


# Spalten, die nachträglich zu `documents` kamen (Metadaten der Veröffentlicher, siehe app/docmeta.py)
DOC_COLUMNS = {
    "sha256": "TEXT", "genre": "TEXT", "doc_date": "TEXT", "words": "INTEGER", "source_set": "TEXT",
}


def migrate(conn: sqlite3.Connection) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    for col, typ in DOC_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
    for col in ("sha256", "genre", "doc_date", "source_set"):
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_doc_{col} ON documents ({col})")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_from ON messages (lower(from_addr))")


def init() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.commit()
    conn.close()
