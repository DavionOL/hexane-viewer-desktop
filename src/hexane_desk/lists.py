"""Lädt öffentliche Referenzlisten ins Benutzerprofil (nur öffentliche Quellen, nur mit Zustimmung des Nutzers):

  officials.json       Politiker der AfD laut abgeordnetenwatch.de (Bundestag, EU-Parlament, Landtage), für die Adressen-Einstufung
  public_domains.json  Domains öffentlicher Stellen laut FragDenStaat, für die Domain-Statistik

Beides dient nur dem Einordnen von Adressen (siehe people.py). Die Listen werden nicht mit dem Programm ausgeliefert, damit
die Lizenzen der Quellen beim Nutzer geprüft werden können; zur Laufzeit ist danach kein Internet nötig.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from . import config

_ctx = None


def say(msg="", **_):
    if _ctx is not None:
        _ctx.log(str(msg))
    else:
        print(msg, flush=True)


def out_dir() -> str:
    d = config.lists_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d)
AW = "https://www.abgeordnetenwatch.de/api/v2"
FDS = "https://fragdenstaat.de/api/v1/publicbody/"
UA = {"User-Agent": "hexane-viewer-desktop/0.1 (research tool; reference lists; https://github.com/DavionOL/hexane-viewer-desktop)"}
# Parlamente bei abgeordnetenwatch: 1 EU, 5 Bundestag, 4 NRW, 9 Mecklenburg-Vorpommern (+ alle weiteren Landtage über party=AfD)
PARLIAMENTS = {1: "EU-Parlament", 5: "Bundestag", 4: "Nordrhein-Westfalen", 9: "Mecklenburg-Vorpommern"}
GENERIC_MAIL = {"gmx.de", "gmx.net", "gmx.at", "web.de", "t-online.de", "gmail.com", "googlemail.com", "yahoo.de",
                "yahoo.com", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de", "freenet.de", "arcor.de",
                "online.de", "aol.com", "icloud.com", "me.com", "live.de", "live.com", "posteo.de", "mailbox.org",
                "protonmail.com", "proton.me", "vodafone.de", "kabelmail.de", "1und1.de", "ewetel.net", "gmx.ch",
                "t-online.com", "mail.de", "email.de", "o2online.de", "netcologne.de", "unitybox.de"}


def get(url: str):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception as e:
            say(f"  Wiederholung ({e})", file=sys.stderr)
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}")


def paged(url: str, size: int = 500):
    start = 0
    while True:
        sep = "&" if "?" in url else "?"
        d = get(f"{url}{sep}range_start={start}&range_end={size}")
        data = d["data"]
        yield from data
        if _ctx is not None:
            _ctx.check()
        if len(data) < size:
            return
        start += size
        time.sleep(0.3)


def officials() -> None:
    people: dict[int, dict] = {}

    def add(pid, label, url, first=None, last=None, mandate=None):
        p = people.setdefault(pid, {"id": pid, "name": label, "first_name": first, "last_name": last,
                                    "url": url, "mandates": []})
        if first and not p["first_name"]:
            p["first_name"], p["last_name"] = first, last
        if mandate and mandate not in p["mandates"]:
            p["mandates"].append(mandate)

    say("AfD-Politiker (aktuell Partei AfD) …")
    for p in paged(f"{AW}/politicians?party[entity.id]=9"):
        add(p["id"], p["label"], p["abgeordnetenwatch_url"], p.get("first_name"), p.get("last_name"))
    say(f"  {len(people)} Personen")

    say("Mandate in Fraktionen der AfD (auch ehemalige Mitglieder) …")
    for par_id, par_name in PARLIAMENTS.items():
        periods = list(paged(f"{AW}/parliament-periods?parliament[entity.id]={par_id}&type=legislature", 100))
        for per in periods:
            for m in paged(f"{AW}/candidacies-mandates?parliament_period={per['id']}&type=mandate"):
                if any("AfD" in (f.get("label") or "") for f in m.get("fraction_membership", [])):
                    pol = m["politician"]
                    add(pol["id"], pol["label"], pol["abgeordnetenwatch_url"], mandate=per["label"])
            say(f"  {per['label']}: bisher {len(people)}")

    missing = [pid for pid, p in people.items() if not p["first_name"]]
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        for p in get(f"{AW}/politicians?id[in]=[{','.join(map(str, chunk))}]&range_end=100")["data"]:
            add(p["id"], p["label"], p["abgeordnetenwatch_url"], p.get("first_name"), p.get("last_name"))

    for p in people.values():
        if not p["first_name"]:
            parts = p["name"].split()
            p["first_name"], p["last_name"] = (parts[0], parts[-1]) if len(parts) > 1 else ("", p["name"])
    out = sorted(people.values(), key=lambda p: (p["last_name"] or "", p["first_name"] or ""))
    with open(os.path.join(out_dir(), "officials.json"), "w") as f:
        json.dump({"source": "abgeordnetenwatch.de (API v2)", "fetched": time.strftime("%Y-%m-%d"),
                   "officials": out}, f, ensure_ascii=False, indent=0)
    say(f"officials.json: {len(out)} Personen")


def host_of(url: str) -> str:
    try:
        h = urllib.parse.urlparse(url if "//" in url else "//" + url).hostname or ""
    except ValueError:
        return ""
    return re.sub(r"^www\d*\.", "", h.lower())


def public_domains() -> None:
    domains: set[str] = set()
    n = 0
    url = FDS + "?format=json&limit=500"
    while url:
        d = get(url)
        for o in d["objects"]:
            n += 1
            h = host_of(o.get("url") or "")
            if h and h.count(".") >= 1 and h not in GENERIC_MAIL:
                domains.add(h)
            alt = o.get("alternative_emails") or ""
            alt_list = [str(x) for x in (alt.values() if isinstance(alt, dict) else alt)] if not isinstance(alt, str) \
                else [x.strip() for x in alt.split(",")]
            for e in [o.get("email")] + alt_list:
                if e and isinstance(e, str) and "@" in e:
                    dom = e.rsplit("@", 1)[1].strip().lower()
                    if dom and dom not in GENERIC_MAIL:
                        domains.add(dom)
        url = d["meta"].get("next")
        if n % 5000 < 500:
            say(f"  {n} Stellen, {len(domains)} Domains", flush=True)
        time.sleep(0.3)
    with open(os.path.join(out_dir(), "public_domains.json"), "w") as f:
        json.dump({"source": "fragdenstaat.de (Verzeichnis öffentlicher Stellen)", "fetched": time.strftime("%Y-%m-%d"),
                   "domains": sorted(domains)}, f, indent=0)
    say(f"public_domains.json: {len(domains)} Domains aus {n} Stellen")


def fetch_all(ctx=None) -> None:
    """Beide Listen laden. Nur aufrufen, wenn der Nutzer zugestimmt hat (Einstellung lists_consent)."""
    global _ctx
    _ctx = ctx
    try:
        if ctx is not None:
            ctx.update(message="Politikerliste laden …")
        officials()
        if ctx is not None:
            ctx.update(message="Behördenliste laden …")
        public_domains()
    finally:
        _ctx = None
