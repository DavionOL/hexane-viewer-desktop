"""Trash-Erkennung: ordnet Mails Gruppen zu (Tabelle msg_junk), damit der Viewer sie ausblenden kann.

    (Schritt „Trash-Gruppen“ der Einrichtung; wiederholbar, nach Änderung von junk_domains.txt erneut ausführen)

Es wird nichts gelöscht. Die Regeln sind bewusst konservativ und einfach lesbar. Die erste passende Gruppe gewinnt.
Antworten/Weiterleitungen (Re:, AW:, Fwd:) werden bei Newsletter, Presse, Shop und Benachrichtigungen nie erfasst, ebenso
nicht Mails mit Finanz-Stichwörtern im Betreff (Spende, Zahlung, Überweisung, Mitglied, Beitrag).
"""
import os
import re

from . import config, db


def like_any(col: str, pats: list[str]) -> str:
    return "(" + " OR ".join(f"{col} LIKE '{p}'" for p in pats) + ")"


NOT_REPLY = ("(subject IS NULL OR (subject NOT LIKE 're:%' AND subject NOT LIKE 'aw:%' AND subject NOT LIKE 'wg:%' "
             "AND subject NOT LIKE 'fwd:%' AND subject NOT LIKE 'fw:%'))")
NOT_FINANCE = ("(subject IS NULL OR NOT (subject LIKE '%spende%' OR subject LIKE '%zahlung%' OR subject LIKE '%überweisung%' "
               "OR subject LIKE '%mitglied%' OR subject LIKE '%beitrag%'))")

F, S = "from_addr", "subject"

PRIVATE_DOMAINS = ["gmx.de", "gmx.net", "gmx.at", "gmx.ch", "web.de", "t-online.de", "gmail.com", "googlemail.com",
                   "yahoo.de", "yahoo.com", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de", "freenet.de",
                   "arcor.de", "online.de", "aol.com", "icloud.com", "me.com", "live.de", "live.com", "posteo.de",
                   "mailbox.org", "protonmail.com", "proton.me", "vodafone.de", "kabelmail.de", "1und1.de", "mail.de",
                   "email.de", "o2online.de", "netcologne.de", "unitybox.de", "tele2.de"]


def custom_cond() -> str:
    """Eigene Liste unerwünschter Absender: data/junk_domains.txt (je Zeile eine Domain oder Adresse, # = Kommentar)."""
    pats = []
    try:
        with open(os.path.join(str(config.lists_dir()), "junk_domains.txt"), encoding="utf-8") as f:
            for line in f:
                e = line.split("#")[0].strip().lower()
                if re.fullmatch(r"[a-z0-9._@-]+", e):
                    pats.append(f"%{e}" if "@" in e else f"%@{e}")
    except OSError:
        pass
    return like_any(F, pats) if pats else "0"

# (Schlüssel, Bezeichnung, Beschreibung, standardmäßig ausgeblendet, SQL-Bedingung)
MAIL_GROUPS = [
    ("bounce", "Zustellfehler", "Mailer-Daemon, Postmaster, „Undeliverable“, „Unzustellbar“", True,
     "(" + like_any(F, ["mailer-daemon@%", "postmaster@%", "%mailer-daemon%"]) + " OR " + like_any(S, [
         "%undeliver%", "%delivery status notification%", "%delivery failure%", "mail delivery failed%", "returned mail%",
         "%unzustellbar%", "%nicht zustellbar%", "%zustellung fehlgeschlagen%", "%failure notice%",
         "%delivery has failed%", "%mail system error%"]) + ")"),
    ("autoreply", "Automatische Antworten", "Abwesenheitsnotizen, Out of Office, „Automatische Antwort:“", True,
     like_any(S, ["automatische antwort%", "abwesenheitsnotiz%", "abwesenheit:%", "out of office%", "auto-reply%",
                  "autoreply%", "automatic reply%", "auto:%", "autoresponder%"])),
    ("spam", "Spam", "Betreff „[SPAM]“ und typische Spam-Wörter", True,
     like_any(S, ["%[spam]%", "%***spam***%", "%viagra%", "%cialis%", "%casino%", "%lotterie%", "%lottery%",
                  "%erbschaft%", "%gewinnbenachrichtigung%", "%kredit ohne%", "%pharmacy%", "%replica%", "%payday%"])),
    ("monitoring", "Monitoring und Systemmeldungen", "Nagios, Zabbix, Icinga, Cron, Logwatch, Fail2ban, root@", True,
     "(" + like_any(F, ["%nagios%", "%zabbix%", "%icinga%", "monit@%", "%logwatch%", "cron@%", "root@%", "%uptimerobot%",
                        "%statuscake%", "%pingdom%", "%fail2ban%", "%munin%", "%smartd%"]) + " OR " + like_any(S, [
         "%** problem%", "%** recovery%", "cron <%", "%logwatch%", "%[alert]%", "%[monit]%", "%fail2ban%",
         "%rkhunter%", "%disk space%"]) + ")"),
    ("presse", "Pressespiegel und Clippings", "Pressespiegel, Presseschau, Medienspiegel, Clippings", True,
     "(" + NOT_REPLY + " AND (" + like_any(S, ["%pressespiegel%", "%presseschau%", "%medienspiegel%", "%pressemonitor%",
                                              "%presse-monitor%", "%clipping%"]) + " OR " + like_any(F, [
         "%pressespiegel%", "%pressemonitor%", "%presse-monitor%", "%medienbeobachtung%"]) + "))"),
    ("newsletter", "Newsletter und Marketing", "Absender oder Betreff mit „Newsletter“, „Mailing“", True,
     "(" + NOT_REPLY + " AND (" + like_any(F, ["%newsletter%", "%mailing@%", "%@mailing.%", "%marketing@%", "news@%",
                                              "%@news.%"]) + " OR " + like_any(S, ["%newsletter%", "%unsubscribe%"]) + "))"),
    ("shop", "Shop und Versand", "Bestellbestätigungen, Sendungsverfolgung, Paketdienste", True,
     "(" + NOT_REPLY + " AND " + NOT_FINANCE + " AND (" + like_any(S, [
         "%bestellbestätigung%", "%bestellbestaetigung%", "%ihre bestellung%", "%order confirmation%", "%your order%",
         "%versandbestätigung%", "%versandbenachrichtigung%", "%sendungsverfolgung%", "%paketankündigung%",
         "%ihr paket%", "%tracking%", "%lieferstatus%"]) + " OR " + like_any(F, [
         "%@dhl.%", "%dhl.de%", "%@dpd.%", "%@hermesworld.%", "%@ups.com", "%@gls-%", "%amazon%"]) + "))"),
    ("paypal_spende", "PayPal-Spendenmeldungen", "formelhafte Meldungen „Sie haben eine Spende erhalten“ (für Finanzfragen einblenden)", True,
     "(" + NOT_REPLY + " AND " + F + " LIKE '%@paypal.%' AND subject LIKE '%spende%')"),
    ("paypal", "PayPal-Benachrichtigungen", "Zahlungsbestätigungen von PayPal; Mails mit „Spende“ im Betreff bleiben sichtbar", True,
     "(" + NOT_REPLY + " AND " + F + " LIKE '%@paypal.%' AND (subject IS NULL OR subject NOT LIKE '%spende%'))"),
    ("social", "Soziale Netzwerke", "Benachrichtigungen von Twitter/X, Facebook, LinkedIn, Xing, Instagram, YouTube", True,
     "(" + NOT_REPLY + " AND " + like_any(F, ["%twitter.com", "%@x.com", "%facebookmail.com", "%@facebook.com",
                                              "%linkedin.com", "%@xing.com", "%instagram.com", "%@youtube.com",
                                              "%@tiktok.com"]) + ")"),
    ("system", "Automatische Benachrichtigungen", "noreply@, notifications@, wordpress@ und ähnliche Absender", True,
     "(" + NOT_REPLY + " AND " + NOT_FINANCE + " AND " + like_any(F, [
         "noreply@%", "no-reply@%", "donotreply@%", "do-not-reply@%", "notification@%", "notifications@%", "mailer@%",
         "wordpress@%", "bounce@%", "%@bounces.%", "system@%"]) + ")"),
    ("custom", "Eigene Liste", "Absender aus junk_domains.txt (von dir gepflegt, Ordner siehe Einrichtung)", True, custom_cond),
    ("fanshop", "Fanshop-Postfächer", "alle übrigen Mails aus den Fanshop-Postfächern (Geldflüsse möglich, daher optional)", False,
     "folder LIKE '%fanshop%'"),
    ("privat", "Absender mit Privatmail-Adresse", "gmx, t-online, web.de, gmail …: meist Bürgerzuschriften; blendet sie aus, "
     "um Absender von Organisationen zu sehen", False, like_any(F, [f"%@{d}" for d in PRIVATE_DOMAINS])),
]

# Dokumente: Bedingung über Art und Wortzahl (Metadaten aus app/docmeta.py), keine eigene Spalte nötig
DOC_GROUPS = [
    ("shipping", "Versand", "Lieferscheine, Versandetiketten (Art SHIPPING)", True, "d.genre = 'SHIPPING'"),
    ("press", "Presse", "Pressespiegel und Artikel (Art PRESS_MONITOR, PRESS_ARTICLE)", True,
     "d.genre IN ('PRESS_MONITOR', 'PRESS_ARTICLE')"),
    ("form", "Formulare", "Formulare und Vordrucke (Art FORM)", False, "d.genre = 'FORM'"),
    ("short", "Kurzdokumente", "weniger als 20 Wörter", False, "(d.words IS NOT NULL AND d.words < 20)"),
    ("invoice", "Rechnungen und Belege", "Art INVOICE, vor allem Fanshop; bei Finanzfragen sichtbar lassen", False,
     "d.genre = 'INVOICE'"),
]

MAIL_KEYS = {g[0] for g in MAIL_GROUPS}
DOC_COND = {g[0]: g[4] for g in DOC_GROUPS}


def main(report: bool = False, ctx=None) -> None:
    from . import jobs
    ctx = ctx or jobs.Ctx()
    print = ctx.log
    db.init()
    conn = db.connect()
    conn.execute("DELETE FROM msg_junk")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"{total} Mails", flush=True)
    unclassified = "NOT EXISTS (SELECT 1 FROM msg_junk j WHERE j.id = messages.id)"
    for gi, (key, label, _desc, _default, cond) in enumerate(MAIL_GROUPS):
        ctx.check() if hasattr(ctx, 'check') else None
        ctx.update(done=gi, total=len(MAIL_GROUPS), message=f'Gruppe: {label}')
        cond = cond() if callable(cond) else cond
        n = conn.execute(f"INSERT INTO msg_junk (id, grp) SELECT id, ? FROM messages WHERE {unclassified} AND {cond}",
                         (key,)).rowcount
        conn.commit()
        print(f"  {label:34s} {n:>8d}  ({100 * n / max(total, 1):.1f} %)", flush=True)
    junk = conn.execute("SELECT COUNT(*) FROM msg_junk").fetchone()[0]
    print(f"Gesamt eingestuft: {junk} von {total} ({100 * junk / max(total, 1):.1f} %)")
    if report:
        print("\nGrößte Absender-Domains ohne Einstufung (nur Zähler):")
        for r in conn.execute("SELECT substr(lower(from_addr), instr(from_addr, '@') + 1) AS dom, COUNT(*) AS n "
                              f"FROM messages WHERE {unclassified} AND from_addr LIKE '%@%' GROUP BY dom "
                              "ORDER BY n DESC LIMIT 25"):
            print(f"  {r['n']:>8d}  {r['dom']}")
    conn.close()
