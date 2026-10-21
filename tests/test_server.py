import time

import pytest
from fastapi.testclient import TestClient

from hexane_desk import config, jobs, server


@pytest.fixture()
def client(indexed):
    server.STATE.update(lan=False, password="")
    c = TestClient(server.app, base_url="http://127.0.0.1")
    c.cookies.set("hexane_token", config.TOKEN)
    return c


def test_guard(indexed):
    server.STATE.update(lan=False, password="")
    bare = TestClient(server.app, base_url="http://127.0.0.1")
    assert bare.get("/api/setup/status").status_code == 401                      # ohne Token
    r = bare.get(f"/?t={config.TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and "hexane_token" in r.headers["set-cookie"] and "t=" not in r.headers["location"]
    other = TestClient(server.app, base_url="http://127.0.0.1")                   # frischer Client ohne Cookie
    assert other.get("/api/setup/status", headers={"Authorization": "Basic eDp5"}).status_code == 401
    evil = TestClient(server.app, base_url="http://evil.example")
    evil.cookies.set("hexane_token", config.TOKEN)
    assert evil.get("/api/setup/status").status_code == 403                      # DNS-Rebinding: fremder Hostname
    server.STATE.update(lan=True, password="geheim")
    lan = TestClient(server.app, base_url="http://192.168.1.5")
    assert lan.get("/api/setup/status").status_code == 401
    assert lan.get("/api/setup/status", headers={"Authorization": "Basic eDpnZWhlaW0="}).status_code == 200
    assert lan.get("/api/fs/list").status_code in (401, 403)                     # Ordnerauswahl im LAN-Modus aus
    server.STATE.update(lan=False, password="")


def test_setup_and_jobs(client):
    st = client.get("/api/setup/status").json()
    assert st["configured"] and st["counts"]["mails"] == 120 and "hexane" in st["mcp_config"]["mcpServers"]
    assert client.post("/api/setup/config", json={"data_dir": "/gibt/es/nicht"}).status_code == 400
    assert client.post("/api/setup/config", json={"mask_external": False}).json()["settings"]["mask_external"] is False
    ov = {s["key"]: s for s in client.get("/api/jobs").json()["steps"]}
    assert ov["mails"]["status"] == "done" and not ov["lists"]["available"]       # Internet nicht erlaubt
    assert client.post("/api/jobs/start", json={"step": "lists"}).status_code == 409
    assert client.post("/api/jobs/start", json={"step": "gibtsnicht"}).status_code == 400
    assert client.post("/api/jobs/start", json={"step": "donations"}).status_code == 200
    for _ in range(100):
        if not client.get("/api/jobs").json()["running"]:
            break
        time.sleep(0.1)
    assert client.get("/api/jobs").json()["jobs"]["donations"]["status"] == "done"


def test_fs_list(client, demo_data):
    d = client.get("/api/fs/list", params={"path": str(demo_data)}).json()
    assert d["looks_like_data"] and {"01_EMAIL", "03_DOCUMENTS"} <= {e["name"] for e in d["entries"]}
    assert client.get("/api/fs/list", params={"path": str(demo_data / "nope")}).status_code == 404


def test_search_marks_headers(client):
    r = client.get("/api/messages", params={"q": "Rechenschaftsbericht", "limit": 5}).json()
    assert r["total"] > 0
    mid = r["items"][0]["id"]
    assert client.get(f"/api/messages/{mid}").json()["body_text"]
    assert client.get(f"/api/messages/{mid}/headers").json()["fields"]
    assert client.get("/api/messages", params={"q": 'von:"anna.beispiel@partei-beispiel.example|bernd.muster@partei-beispiel.example"'}).json()["total"] > 0
    assert client.put(f"/api/marks/mail/{mid}", json={"severity": 4, "category": "finanzen", "note": "x", "verified": 1}).json()["mark"]["severity"] == 4
    assert client.get("/api/messages", params={"q": "Rechenschaftsbericht", "limit": 50}).json()["items"][0]["sev"] in (4, None)
    assert client.get("/api/marks/export", params={"fmt": "md"}).status_code == 200
    assert client.put(f"/api/marks/mail/{mid}", json={"severity": 9}).status_code == 400
    assert client.put(f"/api/marks/mail/{mid}", json={"severity": 0}).json()["mark"] is None
    cat = client.get("/api/messages", params={"cat": "finanzen", "limit": 5}).json()
    assert cat["total"] > 0
    hide = ",".join(g["key"] for g in client.get("/api/junk/groups").json()["mail"] if g["default"])
    assert client.get("/api/messages", params={"hide": hide}).json()["total"] < client.get("/api/messages").json()["total"]


def test_people_and_donations(client):
    p = client.get("/api/people").json()
    assert p["total"] == 2 and p["items"][0]["name"] in ("Anna Beispiel", "Bernd Muster")
    g = client.get("/api/people/person", params={"key": "anna beispiel"}).json()
    assert g["name"] == "Anna Beispiel" and all("@" in x["addr"] or x["addr"].startswith("@") for x in g["to_partners"])
    assert client.get("/api/people/detail", params={"addr": "buerger.eins@gmx.de"}).status_code == 404
    d = client.get("/api/donations/summary").json()
    assert d["total"] > 0 and d["parsed"] == d["total"]


def test_ping_setzt_lebenszeichen(client):
    from hexane_desk import server
    server.STATE["last_ping"] = None
    assert client.get("/api/ping").json() == {"ok": True}
    assert server.STATE["last_ping"] is not None
