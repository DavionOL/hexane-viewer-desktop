"""Adressen-Auswertung mit Datensparsamkeit: wer sind die öffentlichen Akteure im Dump?

    (Schritt „Adressen auswerten“ der Einrichtung)

Stufen:
  1  Amtsträger (Liste von abgeordnetenwatch.de, data/officials.json) und manuell ergänzte öffentliche Personen
     (data/extra_public_figures.txt) -> Profil mit Quelle, Gesprächspartner nur als Stufe-1/2-Adresse oder "@domain"
  2  Adressen auf Parteidomains, die nicht zu Stufe 1 gehören -> nur Zähler (Funktion unklar: Mitarbeiter, Ehrenamt, Shop)
  -  alle anderen Adressen werden NICHT einzeln gespeichert, nur je Domain gezählt (Behörde / Privatmail / sonstige)

Parteizugehörigkeit wird nie aus Mailinhalten abgeleitet. Liest `messages`, schreibt `people`, `pairs`, `domain_stats`
(werden bei jedem Lauf komplett neu aufgebaut).
"""
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict

from . import config, db

TS_MIN, TS_MAX = 631152000, 2051222400      # 1990 .. 2035; alles andere sind kaputte Datumsangaben
PARTY = re.compile(r"afd|alternativefuer|alternative-fuer")
PARLIAMENT = re.compile(r"(^|\.)(bundestag\.de|europarl\.europa\.eu)$|^(landtag|lt-|abgeordnetenhaus|buergerschaft|"
                        r"parlament)|\.(landtag|lt)[\w-]*\.")
GENERIC_MAIL = {"gmx.de", "gmx.net", "gmx.at", "gmx.ch", "web.de", "t-online.de", "gmail.com", "googlemail.com",
                "yahoo.de", "yahoo.com", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de", "freenet.de",
                "arcor.de", "online.de", "aol.com", "icloud.com", "me.com", "live.de", "live.com", "posteo.de",
                "mailbox.org", "protonmail.com", "proton.me", "vodafone.de", "kabelmail.de", "1und1.de", "ewetel.net",
                "mail.de", "email.de", "o2online.de", "netcologne.de", "unitybox.de", "tele2.de"}
TITLES = {"dr", "prof", "mdb", "mdl", "mdep", "med", "jur", "ing", "dipl", "rer", "nat", "phil", "herr", "frau", "von",
          "van", "de", "der", "zu", "graf", "freiherr"}


def norm_forms(s: str) -> set[str]:
    """Kleinschreibung in zwei Varianten: ä->ae (Adressen) und ä->a (Akzente entfernt)."""
    s = s.lower()
    a = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    b = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).replace("ß", "ss")
    return {a, b}


def tokens(s: str) -> set[str]:
    out: set[str] = set()
    for form in norm_forms(s):
        out |= {t for t in re.split(r"[^a-z0-9]+", form) if t}
    return out


def load_officials():
    """Index über Nachnamen-Token -> [(Vorname-Token, [Nachnamen-Token], Quelle, Name)]."""
    by_last: dict[str, list] = defaultdict(list)
    path = os.path.join(str(config.lists_dir()), "officials.json")
    if os.path.exists(path):
        for o in json.load(open(path))["officials"]:
            firsts = tokens((o.get("first_name") or "").split(" ")[0])
            lasts = sorted(t for t in tokens(o.get("last_name") or "") if t not in TITLES)
            if not firsts or not lasts or min(len(f) for f in firsts) < 2:
                continue
            m = ", ".join(o.get("mandates", [])[:2])
            src = f'abgeordnetenwatch.de: {o["url"]}' + (f" ({m})" if m else "")
            for f in firsts:
                by_last[lasts[-1]].append((f, lasts, src, o["name"]))
    return by_last


def load_manual():
    """Zeilen `Name | Notiz | adr1, adr2` aus data/extra_public_figures.txt."""
    names, addrs = [], {}
    path = os.path.join(str(config.lists_dir()), "extra_public_figures.txt")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            name, note = parts[0], (parts[1] if len(parts) > 1 else "")
            src = "manuell ergänzt" + (f": {note}" if note else "")
            if len(name.split()) >= 2:
                names.append((tokens(name) - TITLES, src, name))
            for a in (parts[2].split(",") if len(parts) > 2 else []):
                if "@" in a:
                    addrs[a.strip().lower()] = (src, name)
    return names, addrs


def public_domains() -> set[str]:
    path = os.path.join(str(config.lists_dir()), "public_domains.json")
    return set(json.load(open(path))["domains"]) if os.path.exists(path) else set()


def is_public_body(domain: str, pub: set[str]) -> bool:
    parts = domain.split(".")
    return any(".".join(parts[i:]) in pub for i in range(len(parts) - 1))


def main(ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    print = ctx.log
    db.init()
    conn = db.connect()
    party_re = re.compile(config.settings().party_patterns or PARTY.pattern)
    officials = load_officials()
    manual_names, manual_addrs = load_manual()
    pub = public_domains()

    sent, recv = Counter(), Counter()
    first, last = {}, {}
    names: dict[str, Counter] = defaultdict(Counter)

    def seen(addr, ts):
        if ts is not None and TS_MIN <= ts <= TS_MAX:
            if addr not in first or ts < first[addr]:
                first[addr] = ts
            if addr not in last or ts > last[addr]:
                last[addr] = ts

    def rcpts_of(r):
        return {a.strip().lower() for a in f'{r["to_addrs"] or ""}, {r["cc_addrs"] or ""}'.split(",") if a.strip()}

    n = 0
    for r in conn.execute("SELECT from_name, from_addr, to_addrs, cc_addrs, date_ts FROM messages"):
        n += 1
        src = (r["from_addr"] or "").strip().lower()
        if src:
            sent[src] += 1
            seen(src, r["date_ts"])
            nm = (r["from_name"] or "").strip()
            if nm and nm.lower() != src:
                names[src][nm] += 1
        for a in rcpts_of(r):
            recv[a] += 1
            seen(a, r["date_ts"])
    print(f"Pass 1: {n} Mails, {len(set(sent) | set(recv))} Adressen", flush=True)

    # Einstufung
    level: dict[str, tuple[int, str, str | None]] = {}      # addr -> (Stufe, Quelle, Name)
    for addr in set(sent) | set(recv):
        domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
        on_party = bool(party_re.search(domain))
        on_parl = bool(PARLIAMENT.search(domain))
        if addr in manual_addrs:
            src, nm = manual_addrs[addr]
            level[addr] = (1, src, nm)
            continue
        found = None
        local = addr.rsplit("@", 1)[0]
        cand_tokens = [tokens(local)] + [tokens(nm) for nm, _ in names[addr].most_common(4)]
        if on_party or on_parl:
            for toks in cand_tokens:
                for t in toks:
                    for first_t, lasts, src, label in officials.get(t, ()):
                        if first_t in toks and all(x in toks for x in lasts):
                            found = (1, src, label)
                            break
                    if found:
                        break
                if found:
                    break
        if not found:
            for nm, _ in names[addr].most_common(4):
                toks = tokens(nm) - TITLES
                for mt, src, label in manual_names:
                    if mt and mt <= toks:
                        found = (1, src, label)
        if found:
            level[addr] = found
        elif on_party:
            level[addr] = (2, "Adresse auf Parteidomain; Funktion unklar", None)

    # Pass 2: Beziehungen (nur wenn eine Seite Stufe 1 ist; Externe nur als @domain)
    def key(a: str) -> str:
        return a if a in level else "@" + (a.rsplit("@", 1)[-1] if "@" in a else "unbekannt")

    pairs: Counter = Counter()
    for r in conn.execute("SELECT from_addr, to_addrs, cc_addrs FROM messages"):
        src = (r["from_addr"] or "").strip().lower()
        if not src:
            continue
        src_l1 = src in level and level[src][0] == 1
        for a in rcpts_of(r):
            if src_l1 or (a in level and level[a][0] == 1):
                pairs[(key(src), key(a))] += 1

    # Domain-Statistik für alle, die nicht einzeln geführt werden
    dom_addrs: dict[str, set] = defaultdict(set)
    dom_sent, dom_recv = Counter(), Counter()
    for a in set(sent) | set(recv):
        if a in level:
            continue
        d = a.rsplit("@", 1)[-1] if "@" in a else "unbekannt"
        dom_addrs[d].add(a)
        dom_sent[d] += sent.get(a, 0)
        dom_recv[d] += recv.get(a, 0)

    def kind(d: str) -> str:
        if d in GENERIC_MAIL:
            return "Privatmail"
        return "Behörde/Parlament" if is_public_body(d, pub) else "Sonstige"

    def display_name(a: str, lv) -> str | None:
        if lv[0] == 1 and lv[2]:
            return lv[2]
        return names[a].most_common(1)[0][0] if names.get(a) else None

    people_rows = [(a, display_name(a, lv), a.rsplit("@", 1)[-1] if "@" in a else "", lv[0], lv[1],
                    sent.get(a, 0), recv.get(a, 0), first.get(a), last.get(a)) for a, lv in level.items()]
    dom_rows = [(d, kind(d), len(s), dom_sent[d], dom_recv[d]) for d, s in dom_addrs.items()]

    conn.execute("DELETE FROM people")
    conn.execute("DELETE FROM pairs")
    conn.execute("DELETE FROM domain_stats")
    conn.executemany("INSERT INTO people (addr, name, domain, level, source, n_sent, n_recv, first_ts, last_ts) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", people_rows)
    conn.executemany("INSERT INTO pairs (src, dst, n) VALUES (?,?,?)", ((s, d, c) for (s, d), c in pairs.items()))
    conn.executemany("INSERT INTO domain_stats (domain, kind, n_addrs, n_sent, n_recv) VALUES (?,?,?,?,?)", dom_rows)
    conn.commit()
    conn.close()
    l1 = sum(1 for r in people_rows if r[3] == 1)
    print(f"Fertig: Stufe 1: {l1} Personen, Stufe 2: {len(people_rows) - l1} Adressen, "
          f"{len(dom_rows)} Domains, {len(pairs)} Beziehungen")
