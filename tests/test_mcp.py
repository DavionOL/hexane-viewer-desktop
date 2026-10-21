import asyncio
import json

import pytest

pytest.importorskip("mcp")

from hexane_desk import config, mcp_server


def run(coro):
    return asyncio.run(coro)


def data(res):
    sc = getattr(res, "structured_content", None)
    if sc:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(res.content[0].text)


async def with_client(fn):
    from mcp import Client
    async with Client(mcp_server.build()) as c:
        return await fn(c)


def test_tools_readonly_by_default(indexed):
    async def go(c):
        return [t.name for t in (await c.list_tools()).tools]
    names = run(with_client(go))
    assert {"search_mails", "get_mail", "search_documents", "get_document", "list_people", "donations_summary"} <= set(names)
    assert "set_mark" not in names


def test_masking_and_limits(indexed):
    async def go(c):
        wg = data(await c.call_tool("search_mails", {"query": "Wichtige Information", "hide_trash": False, "limit": 5}))
        big = data(await c.call_tool("search_mails", {"limit": 9999}))
        m = data(await c.call_tool("get_mail", {"id": wg["treffer"][0]["id"], "max_chars": 200}))
        return wg, big, m
    wg, big, m = run(with_client(go))
    assert wg["treffer"] and all("***@" in t["von"] for t in wg["treffer"])           # Außenstehende maskiert
    assert len(big["treffer"]) == mcp_server.MAX_LIMIT
    assert "Fremdtext" in m["hinweis"] and len(m["text"]) <= 200


def test_unmasked_when_disabled(indexed):
    config.save(mask_external=False)

    async def go(c):
        return data(await c.call_tool("search_mails", {"query": "Wichtige Information", "hide_trash": False, "limit": 3}))
    wg = run(with_client(go))
    assert wg["treffer"] and all("***@" not in t["von"] for t in wg["treffer"])


def test_write_tool_requires_opt_in(indexed):
    config.save(allow_write=True)

    async def go(c):
        names = [t.name for t in (await c.list_tools()).tools]
        mid = data(await c.call_tool("search_mails", {"query": "Sitzung", "limit": 1}))["treffer"][0]["id"]
        ok = data(await c.call_tool("set_mark", {"kind": "mail", "id": mid, "severity": 2, "note": "t"}))
        bad = data(await c.call_tool("set_mark", {"kind": "mail", "id": mid, "severity": 9}))
        return names, ok, bad
    names, ok, bad = run(with_client(go))
    assert "set_mark" in names and ok["markierung"]["severity"] == 2 and "fehler" in bad
