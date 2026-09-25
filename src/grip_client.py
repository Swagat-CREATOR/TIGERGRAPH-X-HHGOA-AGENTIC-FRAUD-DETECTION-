"""GRIP (GraphRAG Interoperability Protocol) MCP client — one place to spawn it.

GRIP is the organizers' MCP server: 50 GraphRAG tools over a TigerGraph backend.
Two gotchas cost us a spike, both encoded here so no one hits them again:

1. GRIP reads the secret from ``TIGERGRAPH_GSQL_SECRET`` — NOT ``TIGERGRAPH_SECRET``.
   With the wrong name it silently falls back to its built-in demo graph
   ("[mcp_server] TigerGraph unavailable ('TIGERGRAPH_GSQL_SECRET'); using demo
   adapter"). We set both names to be safe.
2. Stay on stdio (local). Never bind GRIP to a network transport.
3. Write ops (graphrag_ingest / delete / capability_token) need editor+ role.
   GRIP resolves role from a bearer token: the ``admin_token`` argument on those
   tools is compared against the ``GRAPHRAG_ADMIN_TOKEN`` the server booted with
   (mcp_server/contracts/authorization.py:75,148). We spawn GRIP ourselves, so we
   inject our own operator secret (.env ``GRIP_ADMIN_TOKEN``) as that env var and
   hand the same value back via ``admin_token()`` — legitimate operator auth for
   our own server, no token forging. Without it, ingest returns
   {"error":"permission denied"} (role anonymous).

Usage:
    async with grip_toolset() as ts:
        status = await ts.direct_call_tool("graphrag_status", {})
        await ts.direct_call_tool("graphrag_ingest",
                                  {"documents": [...], "admin_token": admin_token()})
"""
from __future__ import annotations

import os

from dotenv import dotenv_values
from pydantic_ai.mcp import FastMCPClient, MCPToolset, StdioTransport


def grip_env(env_path: str = ".env", graph: str | None = None) -> dict[str, str]:
    """Build the process env GRIP needs from our ``.env`` (dotenv_values, not
    load_dotenv — the latter breaks under exec with no calling frame).
    ``graph`` overrides TG_GRAPH (e.g. our FraudInvestigation graph)."""
    e = dotenv_values(env_path)
    secret = e["TG_SECRET"]
    return {
        **os.environ,
        "TIGERGRAPH_HOST": e["TG_HOST"],
        "TIGERGRAPH_USERNAME": e.get("TG_USERNAME", "tigergraph"),
        "TIGERGRAPH_SECRET": secret,
        "TIGERGRAPH_GSQL_SECRET": secret,  # the name GRIP actually reads
        "TIGERGRAPH_GRAPH_NAME": graph or e["TG_GRAPH"],
        "GOOGLE_API_KEY": e["GEMINI_API_KEY"],
        "LLM_MODEL": e["GEMINI_MODEL"],  # keep off retired gemini-2.5-flash
        "GRAPHRAG_ADMIN_TOKEN": e["GRIP_ADMIN_TOKEN"],  # editor+ role for ingest
    }


def admin_token(env_path: str = ".env") -> str:
    """The operator secret to pass as ``admin_token=`` on write tools
    (graphrag_ingest / delete_document / capability_token). Same value we boot
    GRIP's GRAPHRAG_ADMIN_TOKEN with, so resolve_role() maps it to 'admin'."""
    return dotenv_values(env_path)["GRIP_ADMIN_TOKEN"]


def grip_toolset(env_path: str = ".env", graph: str | None = None) -> MCPToolset:
    """A stdio-local GRIP toolset. Use as ``async with grip_toolset() as ts:``."""
    transport = StdioTransport(
        command="grip", args=["--transport", "stdio"], env=grip_env(env_path, graph)
    )
    return MCPToolset(FastMCPClient(transport))


if __name__ == "__main__":
    import asyncio

    async def _smoke() -> None:
        async with grip_toolset() as ts:
            r = await ts.direct_call_tool("graphrag_status", {})
            text = str(r)
            assert "tigergraph" in text and "demo" not in text.lower(), text
            print("grip_client self-check OK — connected to real backend")

    asyncio.run(_smoke())

