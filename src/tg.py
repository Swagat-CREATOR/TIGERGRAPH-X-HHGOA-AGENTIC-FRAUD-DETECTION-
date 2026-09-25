"""TigerGraph connection — one place, reused by the loader and the direct-GSQL
adapter fallback. GRIP owns the agent-facing MCP interface; this owns DDL + bulk
load (the internal reliability layer behind the same tool signatures).

dotenv_values, not load_dotenv (load_dotenv breaks under exec with no frame).
"""
from __future__ import annotations

from dotenv import dotenv_values


def connect(graph: str | None = None):
    """Return a pyTigerGraph connection with a fresh REST token.

    graph=None connects at the instance level (needed to CREATE a graph before
    it exists). Pass a graph name once it exists to run graph-scoped GSQL.
    """
    import pyTigerGraph as tg

    e = dotenv_values(".env")
    conn = tg.TigerGraphConnection(
        host=e["TG_HOST"],
        username=e.get("TG_USERNAME", "tigergraph"),
        gsqlSecret=e["TG_SECRET"],
        graphname=graph or "",
    )
    # Savanna: mint a REST++ token from the secret (works without a password).
    conn.getToken(e["TG_SECRET"])
    return conn


if __name__ == "__main__":
    c = connect()
    print("version:", c.getVer())
    print("graphs / ls:", c.gsql("SHOW GRAPH *", options=[])[:600])

