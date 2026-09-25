"""Create (or recreate) the FraudInvestigation graph from graph_schema.gsql.

Idempotent: drops the graph first so re-runs start clean. Leaves the demo
Transaction_Fraud graph untouched (our types are local to this graph).
"""
from __future__ import annotations

from src.tg import connect


def main() -> None:
    c = connect()
    # Clean slate — ignore "not exist" on first run.
    for stmt in ("DROP GRAPH FraudInvestigation",):
        try:
            print("drop:", c.gsql(stmt)[:200])
        except Exception as e:  # noqa: BLE001
            print("drop skipped:", str(e)[:200])
    script = open("src/graph_schema.gsql", encoding="utf-8").read()
    out = c.gsql(script)
    print(out[-1500:])


if __name__ == "__main__":
    main()

