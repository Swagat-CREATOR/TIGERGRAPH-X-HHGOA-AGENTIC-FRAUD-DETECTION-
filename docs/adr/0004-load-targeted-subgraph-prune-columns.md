# Load a targeted subgraph (not the full population), prune V-columns

For the 6–7 hour build, do **not** bulk-load all 590,742 transactions into Savanna. Load a **targeted closure**: every Card + Customer named in `case_pack.csv` and `closed_cases_history.csv`, with their full Transaction + identity history; then expand one hop along the high-specificity shared identifiers (DeviceProfile, recipient EmailDomain) so connected cards come along. Region/email neighbor breadth is bounded to the Nov–Dec exam window. Keep only the columns the agent reasons over; drop `V1–V339`.

**Why:** Investigation accuracy + Next-Best-Action are 50% of the score and hinge on connected-card links (e.g. HHG-014, "several cards, same unusual device"), so we keep the shared-origin closure around the scored entities. But a full ~708 MB cloud load is a *fatal time risk* in a 6–7 hour build and stresses the free tier. The 20 exam cases are the only scored targets; a shared-origin ring disjoint from every case-pack and closed card is irrelevant to them — so the closure loses no scoring-relevant connectivity while loading in minutes instead of hours.

**Consequences:** any transaction or feature not loaded is fetchable out-of-graph from `transactions.csv` by `TransactionID` for a one-off evidence need. The graph client stays behind a thin abstraction, so a fuller load — or Community Edition locally — is a later swap if time allows.

**Supersedes** the earlier full-population intent, which assumed an open-ended timeline. **Rejected:** full population (load-time risk fatal to the budget for negligible scoring gain), case-pack-only (misses the connected cards the highest-value cases depend on).

