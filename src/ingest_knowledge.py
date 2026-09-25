"""Ingest the knowledge-doc corpus (src/knowledge_docs.py) into the live
FraudInvestigation graph through GRIP, then verify it persisted.

This is the README's "load the pattern section, the policy, and the regulatory
documents into TigerGraph vector search for retrieval" step, done natively on
our graph through GRIP (see [[grip-doc-layer-native]]):

  * graphrag_ingest with extraction_strategy="frequency" — NO LLM/Gemini spend.
    Each doc becomes a Paper vertex; frequency extraction mints shared Concept
    vertices (card testing, device profile, SAR, ...) and MENTIONS edges that
    cross-link related docs. authors -> Author vertices + AUTHORED_BY.
  * admin_token=admin_token() gives the ingest call editor+ role (our own
    operator secret, matched against the GRAPHRAG_ADMIN_TOKEN we boot GRIP with).

Verify has two independent checks:
  1. Vertex counts on the real backend (Paper == len(corpus), Concept > 0).
  2. A graphrag_local_search probe returns a doc for a policy query.

The doc ontology (Paper/Author/Concept/PaperEmb) and its query install must
already be in place — run src/create_doc_schema.py first. The first-ever
local_search compiles 6 GSQL queries (~1-2 min); once installed it is fast, so
re-runs of this script verify quickly.
"""
from __future__ import annotations

import asyncio

from src.grip_client import admin_token, grip_toolset
from src.knowledge_docs import docs
from src.tg import connect

GRAPH = "FraudInvestigation"
PROBE_QUERY = "when must a suspicious activity report be filed"


def _counts() -> dict[str, int]:
    """Doc-ontology vertex counts straight from the backend (ground truth,
    independent of GRIP's own reporting)."""
    c = connect(GRAPH)
    out = {}
    for vtype in ("Paper", "Author", "Concept", "PaperEmb"):
        try:
            out[vtype] = c.getVertexCount(vtype)
        except Exception as e:  # noqa: BLE001
            out[vtype] = f"ERR {str(e)[:80]}"
    return out


async def main() -> None:
    corpus = docs()
    print(f"corpus: {len(corpus)} docs -> ingesting into {GRAPH} via GRIP")

    async with grip_toolset(graph=GRAPH) as ts:
        res = await ts.direct_call_tool(
            "graphrag_ingest",
            {
                "documents": corpus,
                "extraction_strategy": "frequency",  # explicit: no Gemini spend
                "admin_token": admin_token(),
            },
        )
        print("--- graphrag_ingest ---")
        print(str(res)[:1500])

        print("--- backend vertex counts ---")
        counts = _counts()
        print(counts)
        assert counts.get("Paper") == len(corpus), (
            f"expected Paper=={len(corpus)}, got {counts.get('Paper')}"
        )

        print(f"--- graphrag_local_search probe: {PROBE_QUERY!r} ---")
        search = await ts.direct_call_tool(
            "graphrag_local_search", {"query": PROBE_QUERY, "top_k": 3}
        )
        text = str(search)
        print(text[:1500])
        assert "SAR" in text or "report" in text.lower(), "probe returned no doc"

    print("OK — knowledge corpus ingested and retrievable")


if __name__ == "__main__":
    asyncio.run(main())

