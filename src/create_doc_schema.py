"""Add GRIP's Paper/Author/Concept/PaperEmb doc ontology to the live
FraudInvestigation graph (src/doc_schema.gsql). Additive and idempotent —
schema-change jobs use ADD/ALTER, so re-running is safe once the types exist
(GSQL reports the job already applied rather than corrupting anything). Does
NOT drop the graph, unlike create_graph.py.

The two schema-change jobs are submitted separately: the vector ALTER targets
PaperEmb, which must be committed by the first job before the second runs.
"""
from __future__ import annotations

from src.tg import connect

VERTEX_JOB, VECTOR_JOB = "fi_docs", "fi_docs_vec"


def _run_job(c, header: str, body: str, run_stmt: str) -> None:
    script = f"USE GRAPH FraudInvestigation\n{body}\n{run_stmt}"
    print(f"--- {header} ---")
    print(c.gsql(script)[-1200:])


def main() -> None:
    c = connect()
    text = open("src/doc_schema.gsql", encoding="utf-8").read()
    # Split the file's two USE/CREATE/RUN blocks on the second USE GRAPH.
    blocks = text.split("USE GRAPH FraudInvestigation")
    # blocks[0] = header comment; blocks[1] = vertex job; blocks[2] = vector job
    for name, blk in ((VERTEX_JOB, blocks[1]), (VECTOR_JOB, blocks[2])):
        try:
            out = c.gsql("USE GRAPH FraudInvestigation" + blk)
            print(f"--- {name} ---\n{out[-1200:]}")
        except Exception as e:  # noqa: BLE001
            print(f"--- {name} FAILED ---\n{str(e)[:600]}")


if __name__ == "__main__":
    main()

