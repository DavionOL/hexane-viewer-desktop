"""Kommandozeile: hexane-desk [desktop|serve|launch|install-launcher|index|demo|doctor|mcp]"""
import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser

from . import __version__, config, datasets


def _free_port(start: int) -> int:
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("Kein freier Port gefunden")


def _start_server(port: int, lan: bool, password: str):
    import uvicorn
    from . import server
    server.STATE["lan"] = lan
    server.STATE["password"] = password
    cfg = uvicorn.Config(server.app, host="0.0.0.0" if lan else "127.0.0.1", port=port, log_level="warning",
                         log_config=None)             # funktioniert auch ohne Konsole (Windows-Fenster-Programm)
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True, name="uvicorn")
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    return srv


def cmd_serve(a):
    port = a.port or _free_port(config.settings().port)
    if a.lan and not a.password:
        sys.exit("Im Netzwerk-Modus (--lan) ist ein Passwort Pflicht: --password GEHEIM")
    srv = _start_server(port, a.lan, a.password or "")
    url = f"http://127.0.0.1:{port}/?t={config.TOKEN}"
    print(f"hexane-desk {__version__} läuft.\nOben diesen Link im Browser öffnen (enthält das Zugriffstoken):\n  {url}", flush=True)
    if a.lan:
        print(f"Im Netzwerk erreichbar auf Port {port} (Passwort erforderlich). Nur in vertrauenswürdigen Netzen verwenden.", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.should_exit = True


def cmd_launch(a):
    """Für den Programm-Starter: ein Klick öffnet den Browser; zweiter Klick öffnet nur den Tab; Ende, wenn der Tab zu ist."""
    from . import jobs, launcher, server
    url = launcher.find_running()
    if url:
        webbrowser.open(url)
        return
    port = _free_port(config.settings().port)
    srv = _start_server(port, False, "")
    url = f"http://127.0.0.1:{port}/?t={config.TOKEN}"
    launcher.remember(url, port)
    webbrowser.open(url)
    try:
        launcher.wait_until_closed(server.STATE, lambda: jobs.running() is not None)
    except KeyboardInterrupt:
        pass
    finally:
        launcher.forget()
        srv.should_exit = True


def cmd_install_launcher(a):
    if sys.platform != "linux":
        sys.exit("Der Programm-Starter wird nur unter Linux angelegt (Windows: Installer, macOS: Programm in den Ordner „Programme\" ziehen).")
    from . import launcher
    print(f"Starter angelegt: {launcher.install_linux()}\nJetzt im Anwendungsmenü nach „Hexane Desk\" suchen.")


def _webview2_ok() -> bool:
    """Windows: ist die Edge-WebView2-Laufzeit installiert? (Auf anderen Systemen immer wahr.)"""
    if os.name != "nt":
        return True
    import winreg
    guid = "Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + guid), (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + guid),
                       (winreg.HKEY_CURRENT_USER, "Software\\" + guid)):
        try:
            with winreg.OpenKey(hive, path) as k:
                v = winreg.QueryValueEx(k, "pv")[0]
                if v and v != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def cmd_desktop(a):
    if not _webview2_ok():
        print("Die Edge-WebView2-Laufzeit fehlt (nötig für das Programmfenster). Ich starte stattdessen den Browser-Modus.", flush=True)
        return cmd_serve(a)
    try:
        import webview
    except ImportError:
        print("Das Desktop-Fenster braucht pywebview:  pip install \"hexane-desk[desktop]\"\nStatt dessen starte ich den Browser-Modus.")
        return cmd_serve(a)
    port = a.port or _free_port(config.settings().port)
    srv = _start_server(port, False, "")

    class Api:
        def choose_folder(self):
            res = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            return res[0] if res else None

    webview.create_window("Hexane Desk", f"http://127.0.0.1:{port}/?t={config.TOKEN}", js_api=Api(), width=1440, height=900)
    webview.start()
    srv.should_exit = True


def cmd_index(a):
    """Einrichtung ohne Oberfläche: Datenordner setzen und Schritte nacheinander ausführen."""
    from . import db, jobs
    if a.data:
        config.save(data_dir=str(__import__("pathlib").Path(a.data).resolve()))
    if a.consent_lists:
        config.save(lists_consent=True)
    root = config.data_root()
    if not root:
        sys.exit("Kein Datenordner gewählt: hexane-desk index --data PFAD")
    db.init()
    steps = a.steps or jobs.RECOMMENDED
    parts = datasets.detect(root, fresh=True)["parts"]
    caps = datasets.capabilities()
    for key in steps:
        st = jobs.STEPS[key]
        ok, why = jobs.availability(st, jobs.persisted(), caps, parts)
        if not ok:
            print(f"übersprungen: {st.label} ({why})")
            continue
        print(f"== {st.label}")
        st.run(jobs.Ctx())
        jobs._persist(key, "done", "")


def cmd_demo(a):
    from . import demo
    out = demo.make(a.out, n_mails=a.mails)
    print(f"Demo-Datensatz (erfunden) liegt in {out}\nIm Programm als Datenordner wählen oder:  hexane-desk index --data {out}")


def cmd_doctor(a):
    s = config.settings()
    print(f"hexane-desk {__version__}\nKonfiguration : {config.settings_file()}\nIndex         : {config.index_path()}\n"
          f"Datenordner   : {s.data_dir or '(nicht gewählt)'}\nHilfsprogramme: {datasets.capabilities()}")


def cmd_mcp(a):
    try:
        from . import mcp_server
    except ImportError:
        sys.exit("Der MCP-Server braucht das Paket mcp:  pip install \"hexane-desk[mcp]\"")
    mcp_server.run(a.transport)


def main(argv=None):
    multiprocessing.freeze_support()                   # nötig für gepackte Programme unter Windows
    p = argparse.ArgumentParser(prog="hexane-desk", description="Recherche-Werkzeug für den hexane-Datensatz")
    sub = p.add_subparsers(dest="cmd")
    for name, fn, help_ in (("desktop", cmd_desktop, "Desktop-Fenster (Standard)"), ("serve", cmd_serve, "Nur lokaler Server, im Browser öffnen")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--port", type=int, default=0)
        sp.add_argument("--no-browser", action="store_true")
        sp.add_argument("--lan", action="store_true", help="auch im Netzwerk erreichbar (nur mit Passwort)")
        sp.add_argument("--password", default="")
        sp.set_defaults(fn=fn)
    sub.add_parser("launch", help="Starter-Modus: Browser öffnen, Ende wenn der Tab geschlossen wird").set_defaults(fn=cmd_launch)
    sub.add_parser("install-launcher", help="Linux: Eintrag im Anwendungsmenü anlegen").set_defaults(fn=cmd_install_launcher)
    sp = sub.add_parser("index", help="Datensatz ohne Oberfläche einlesen")
    sp.add_argument("--data", help="Wurzelordner des Datensatzes")
    sp.add_argument("--steps", nargs="*", help="Schritte (Standard: alle empfohlenen)")
    sp.add_argument("--consent-lists", action="store_true", help="Laden öffentlicher Referenzlisten erlauben")
    sp.set_defaults(fn=cmd_index)
    sp = sub.add_parser("demo", help="erfundenen Demo-Datensatz erzeugen")
    sp.add_argument("--out", required=True)
    sp.add_argument("--mails", type=int, default=300)
    sp.set_defaults(fn=cmd_demo)
    sub.add_parser("doctor", help="Konfiguration und Hilfsprogramme anzeigen").set_defaults(fn=cmd_doctor)
    sp = sub.add_parser("mcp", help="MCP-Server für KI-Clients starten")
    sp.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    sp.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    if not a.cmd:
        a = p.parse_args(["desktop"])
    a.fn(a)


if __name__ == "__main__":
    main()
