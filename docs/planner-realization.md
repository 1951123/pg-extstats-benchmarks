# Planner realization contract

Statistics configuration artifacts have three separate notions of order.

* **Membership identity** is the selected candidate ID subset.
* **Serialization order** is the lexical order used by JSON and the
  configuration digest.  It makes equivalent input permutations produce one
  stable artifact identity.
* **Planner realization order** is the order exposed to PostgreSQL's
  catalogless hypothetical-statistics layer.  It is the frozen
  `advisor-precedence-v1` order: kind (`mcv` before `fd`), number of columns,
  relation column positions, column names, then candidate ID.

The last order is semantic for native CE replay.  PostgreSQL constructs the
relation statistic list from the active hypothetical order, and
`choose_best_statistics()` uses list order as the final tie-breaker for
greedy-cover selection.  Therefore an equivalent membership activated in a
different order can produce different Plan Rows.  The benchmark provider
resolves a persisted lexical `StatisticsConfiguration` through the referenced
repository and relation metadata before activation; lexical serialization is
never used directly as planner order.

Catalogless synthetic OIDs are derived from `(relation OID, kind,
candidate_id)` with collision probing, so they are diagnostics rather than
durable artifact identity and do not depend on registration order.  The
provider still records the repository registration order and selected OID map
in replay provenance.

The canonical replay contract is consequently:

```
membership IDs -> advisor-precedence-v1 -> synthetic OIDs -> PostgreSQL CE
```

The contract does not assert permutation invariance.  It asserts that a
persisted configuration replays the same realization used by the advisor
search.  The top-100 P1/L/P2 diagnostic is stored externally under
`census-advisor-top100-replay-provenance-v1`.
