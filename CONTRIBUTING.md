# Contributing and commit rules

## What belongs in the repository

Commit source code, GSQL schemas, ADRs, documentation, the static UI, and the
generated graded case outputs/traces that demonstrate the 20-case deliverable.
Do not commit:

- `.env` or any API key, token, password, or TigerGraph secret;
- the external IEEE-CIS dataset or any other raw CSV/data dump;
- local virtual environments, model/embedding caches, Python bytecode, or
  `work/` scratch files;
- credentials copied from local tooling or browser sessions.

`.gitignore` is the first line of defense; inspect `git status` before every
commit and review the staged diff manually.

## Commit format

Use a short imperative subject with a focused scope, for example:

```text
docs: add end-to-end runbook and architecture notes
fix: preserve graph-write fallback when TigerGraph is unavailable
feat: add agentic GraphRAG case tool
```

Keep unrelated changes in separate commits. Do not rewrite shared history or
force-push `main` unless the repository owner explicitly requests it.

## Authorship rule

The human/project owner remains the commit author. Do not add a
`Co-authored-by: Claude` trailer or any other unrequested co-author trailer.
Historical planning notes may mention tools or reviewers; that is not commit
authorship and should not be rewritten solely for this rule.

Before publishing, verify:

```bash
git log -1 --format=fuller
git show -s --format=%B HEAD
git status --short
```

The commit message must contain no `Co-authored-by:` line unless the owner
explicitly asks for one.

## Review checklist

- secrets and raw datasets are absent from the staged diff;
- README/runbook commands match the current entry points;
- `python -m src.build_ui` succeeds after case outputs exist;
- P3 output contains the answer and `.trace.json` for each completed case;
- no new code bypasses GRIP/MCP as the primary graph interface;
- policy routes, schema validation, SAR rules, and graph write-back remain
  covered by the existing shared spine;
- commit author and message are verified before push.

