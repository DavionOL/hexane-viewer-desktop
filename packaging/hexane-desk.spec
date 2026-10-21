# PyInstaller-Spezifikation:  pyinstaller packaging/hexane-desk.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("hexane_desk")                 # static/ (Oberfläche) und templates/
hidden = collect_submodules("uvicorn") + collect_submodules("hexane_desk")
for optional in ("mcp", "webview"):                       # nur einbinden, wenn installiert
    try:
        __import__(optional)
        hidden += collect_submodules(optional, filter=lambda n: not n.startswith("mcp.cli"))   # mcp.cli braucht ein Zusatzpaket
        datas += collect_data_files(optional)
    except ImportError:
        pass

a = Analysis(["entry.py"], pathex=["../src"], datas=datas, hiddenimports=hidden, excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="hexane-desk", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="hexane-desk")
