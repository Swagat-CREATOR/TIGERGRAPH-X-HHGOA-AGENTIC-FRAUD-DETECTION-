"""Knowledge retrieval through GRIP, exposed synchronously.

GRIP is async and spawns a subprocess; we do NOT want to pay that spawn per
query across a 20-case x N-tool run. So KnowledgeIndex runs one long-lived GRIP
session on a dedicated background event-loop thread and hands the rest of the
codebase a plain synchronous ``search(query)`` — the pipelines and the P3 tool
loop stay fully sync while retrieval still goes through GRIP's graphrag_local_
search (keyword + graph relevance over the Paper/Concept docs we ingested).

This is the README's "TigerGraph vector search for retrieval" seam, honoured via
GRIP rather than a hand-rolled index (see [[grip-doc-layer-native]]). If GRIP is
unavailable the index degrades to a GSQL keyword scan over Paper so a pipeline
run never hard-fails; the degrade is reported in ``backend``.
"""
from __future__ import annotations

import asyncio
import threading

from src.grip_client import admin_token, grip_toolset  # noqa: F401  (admin_token reserved)
from src.tg import connect

GRAPH = "FraudInvestigation"


class KnowledgeIndex:
    def __init__(self, graph: str = GRAPH) -> None:
        self.graph = graph
        self.backend = "grip"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ts = None
        self._cm = None
        try:
            self._submit(self._aopen()).result(timeout=60)
        except Exception as ex:  # noqa: BLE001
            self.backend = f"gsql-fallback ({str(ex)[:60]})"

    # placeholder-knowledge

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _aopen(self) -> None:
        self._cm = grip_toolset(graph=self.graph)
        self._ts = await self._cm.__aenter__()
        # warm the query install (first search compiles 6 GSQL queries)
        await self._ts.direct_call_tool(
            "graphrag_local_search", {"query": "policy", "top_k": 1})

    async def _asearch(self, query: str, top_k: int) -> dict:
        return await self._ts.direct_call_tool(
            "graphrag_local_search", {"query": query, "top_k": top_k})

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return [{id, title, snippet, score}] most relevant to `query`.

        GRIP's frequency search ties most candidates at relevance 1.0 (no
        embeddings), so ordering among ties is arbitrary. We over-fetch and
        re-rank by query-term overlap on title+snippet, keeping GRIP's score as
        the tie-breaker — deterministic, and it surfaces the definitional doc."""
        fetch = max(top_k * 4, 12)
        hits: list[dict] = []
        if self.backend == "grip":
            try:
                raw = self._submit(self._asearch(query, fetch)).result(timeout=90)
                hits = self._parse_grip(raw, fetch)
            except Exception:  # noqa: BLE001
                hits = []
        if not hits:
            hits = self._gsql_search(query, fetch)
        return self._rerank(query, hits, top_k)

    @staticmethod
    def _rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
        terms = [t for t in
                 "".join(c.lower() if c.isalnum() else " " for c in query).split()
                 if len(t) > 3]
        def overlap(h: dict) -> int:
            blob = f"{h.get('title','')} {h.get('snippet','')}".lower()
            return sum(blob.count(t) for t in terms)
        ranked = sorted(hits, key=lambda h: (overlap(h), h.get("score", 0.0)),
                        reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _parse_grip(raw, top_k: int) -> list[dict]:
        import json
        text = raw if isinstance(raw, str) else getattr(raw, "text", None) or str(raw)
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return []
        ents = (data.get("results", {}) or {}).get("entities", []) or []
        out = []
        for e in ents[:top_k]:
            props = e.get("properties", {}) or {}
            out.append({"id": e.get("id"), "title": e.get("name") or props.get("title"),
                        "snippet": (props.get("abstract") or "")[:500],
                        "score": e.get("relevance_score", 0.0)})
        return out

    def _gsql_search(self, query: str, top_k: int) -> list[dict]:
        """Degrade path: token-overlap scan over Paper via GSQL."""
        terms = [t.lower() for t in query.split() if len(t) > 3]
        res = connect(self.graph).runInterpretedQuery(
            "INTERPRET QUERY () FOR GRAPH FraudInvestigation {"
            " R = SELECT p FROM Paper:p LIMIT 100; PRINT R; }")
        papers = [v["attributes"] for v in res[0]["R"]] if res and res[0]["R"] else []
        scored = []
        for p in papers:
            blob = f"{p.get('title','')} {p.get('abstract','')}".lower()
            score = sum(blob.count(t) for t in terms)
            if score:
                scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        return [{"id": p["id"], "title": p.get("title"),
                 "snippet": (p.get("abstract") or "")[:500], "score": float(s)}
                for s, p in scored[:top_k]]

    def close(self) -> None:
        if self._cm is not None:
            try:
                self._submit(self._cm.__aexit__(None, None, None)).result(timeout=30)
            except Exception:  # noqa: BLE001
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)


if __name__ == "__main__":
    ki = KnowledgeIndex()
    print("backend:", ki.backend)
    for hit in ki.search("three small online authorizations then a larger purchase", 3):
        print(f"  {hit['score']:.3f} {hit['id']}: {hit['title']}")
    ki.close()

