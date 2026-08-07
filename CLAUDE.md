# CLAUDE.md

Guidance for Claude Code working in this repository. Read fully before writing code.

---

## 1. Project

**Feature Store Query & Reporting Agent** is a Vietnamese BI agent over approved
feature-store tables.

It has two modes:

1. **On-demand analyst** — users ask in Vietnamese; the Agent retrieves approved
   features, plans an approved query path, generates and validates SQL, executes it
   read-only, and returns a KPI card, table, or simple chart.
2. **Proactive reporter** — the next workstream after Sprint 2; deterministic jobs
   scan approved KPIs, detect notable changes, and let an LLM narrate validated
   evidence in Vietnamese.

**Boundary:** the Agent consumes approved features. It does not curate, approve,
keep/drop, or redefine features. Raw tables are never queryable by the user-facing
Agent.

---

## 2. General coding behavior

These rules apply to every task unless a project-specific rule below is stricter.

### 2.1 Think before coding

Do not assume and do not hide uncertainty.

Before implementing:

- State material assumptions explicitly.
- If multiple interpretations exist, surface them instead of choosing silently.
- If a simpler solution exists, say so and prefer it.
- If the request is unclear, stop and identify exactly what is unclear.
- Ask before implementing when ambiguity could change behavior, schema, semantics,
  security, or evaluation.

For trivial tasks, use judgment and avoid unnecessary ceremony.

### 2.2 Simplicity first

Write the minimum code required to solve the requested problem.

- Do not add features beyond the request.
- Do not introduce abstractions for one-off logic.
- Do not add speculative flexibility or configurability.
- Do not add error handling for impossible states.
- If a solution is substantially more complex than necessary, simplify it before
  finishing.

A senior engineer should be able to explain why every abstraction exists.

### 2.3 Surgical changes

Touch only what is required.

When editing existing code:

- Do not refactor adjacent code unless the request requires it.
- Do not reformat unrelated files or sections.
- Match the repository's existing style.
- Do not remove unrelated dead code.
- Mention unrelated issues instead of fixing them silently.

When your own changes create unused imports, variables, functions, files, or
configuration, remove only those new orphans.

Every changed line should trace directly to the requested outcome.

### 2.4 Goal-driven execution

Turn the request into explicit, verifiable goals.

Examples:

- “Add validation” → write invalid-input tests, then make them pass.
- “Fix the bug” → reproduce it with a test, then make the test pass.
- “Refactor X” → prove behavior with tests before and after.

For multi-step work, state a short plan in this format:

```text
1. Step → verify: check
2. Step → verify: check
3. Step → verify: check
```

Continue until the stated checks pass. Do not stop at “implemented” without
verification.

### 2.5 Expected effect

These guidelines should result in:

- smaller diffs;
- fewer unrelated changes;
- fewer rewrites caused by overengineering;
- clarification before implementation when ambiguity matters;
- testable success criteria for non-trivial work.

---

## 3. Current status

Sprint 1 and Sprint 2 are complete.

### Sprint 1 delivered

- Feature inventory and Vietnamese semantic metadata.
- Tiered feature retrieval.
- Text-to-SQL generation.
- SQL guard and read-only execution.
- Mock data and golden-set evaluation.
- Sprint 1 safety guardrails.

### Sprint 2 delivered

- GSM ↔ VinFast Cross-BU queries.
- `feature.customer_cross_bu_feature`.
- VinFast order-status history and vehicle-handover sources.
- Buyer/owner separation.
- Point-in-time behavior.
- `metadata.join_catalog` and Join Planner.
- Generator v2 and Guard v2.
- Short-term clarification state.
- Result-shape selection.
- KPI-card and line-chart UI.
- SQL, confidence, warning, join explanation, and cancel action.
- Sprint 2 benchmark for Cross-BU, buyer/owner, PIT, multi-turn, and join safety.

Do not rebuild these foundations unless fixing a measured regression or an
approved requirement.

---

## 4. Canonical decisions

- Supported Business Units: **GSM and VinFast only**.
- Cross-BU means GSM ↔ VinFast.
- `global_loyalty`, loyalty-led Cross-PnL, and other PnLs are out of scope.
- Cross-BU analysis uses a precomputed approved feature table.
- Historical semantics use event time, not ingest time.
- Vehicle buyer and vehicle owner are different concepts.
- Raw data is inaccessible to the query Agent.
- Memory is short-term pending clarification only.
- The current prototype does not use Redis.
- There is no global company-level aggregate feature layer.
- YAML is the semantic authoring source.
- PostgreSQL metadata is the runtime projection.
- Semantic sync is one-way: YAML → validation → DB catalog.

Read before changing related behavior:

```text
vehicle_owner_semantics.md
join_policy.md
short_term_state_contract.md

adr/0001-cross-bu-precomputed-table.md
adr/0002-event-time-not-ingest-time.md
adr/0003-no-global-aggregate-layer-in-sprint-2.md
```

---

## 5. Data scope

### Queryable feature tables

| Table | Role | Grain |
|---|---|---|
| `feature.gsm_transaction` | GSM transaction features | customer + snapshot |
| `feature.vinfast_transaction` | VinFast order and buyer/owner features | customer + snapshot |
| `feature.customer_cross_bu_feature` | Approved GSM–VinFast bridge | customer + snapshot |

Known counts:

- GSM: 167 features.
- VinFast: 186 original features plus 7 Sprint 2 buyer/owner columns.
- Cross-BU count must be read from the physical schema or generated feature spec.

Do not maintain a single hand-written total. Tests must reconcile physical schema,
feature spec, YAML, and DB catalog.

### Raw tables

```text
raw.customers
raw.date_dim
raw.gsm_trips
raw.vinfast_orders
raw.vinfast_order_status_history
raw.vinfast_vehicle_handover
```

Raw may be used by controlled feature-building and data-quality pipelines only.

The Agent must reject raw references inside direct SQL, CTEs, subqueries, aliases,
quoted identifiers, `UNION`, or joins.

### Runtime metadata

```text
metadata.feature_catalog
metadata.feature_synonyms
metadata.business_terms
metadata.term_feature_map
metadata.queryable_feature_view
metadata.join_catalog
```

Do not add `metadata.visualization_config` without an approved ADR.

---

## 6. Semantic layer

`feature_describer.py` generates Vietnamese descriptions and search keywords from
feature names.

Rules:

- Do not hand-write large sets of descriptions.
- Extend shared dictionaries such as `METRICS`, `SEGMENTS`, `STATUS`, and
  `SYNONYMS`, then regenerate.
- Grow Vietnamese synonyms from real business language.
- Flag unknown terms rather than inventing meanings.
- `wo` and `nvso` remain unverified unless repository contracts confirm them.
- Semantic changes start in YAML, then deploy to the DB catalog.
- Do not edit YAML and DB metadata independently.

CI should fail when:

- a queryable physical feature is absent from YAML;
- a YAML feature is absent from the schema;
- a DB catalog entry is absent from the schema;
- a queryable feature lacks a Vietnamese description;
- a restricted feature enters the queryable view;
- buyer is described as owner;
- owner is not derived from handover evidence.

---

## 7. Query architecture

```text
Vietnamese message
→ pending-state check
→ intent and slot parsing
→ clarification when required
→ GSM / VinFast / Cross-BU routing
→ tiered retrieval
→ approved join planning
→ SQL generation
→ AST validation
→ read-only execution
→ result-shape selection
→ coverage analysis
→ Vietnamese answer + SQL + confidence + warnings + join explanation
```

### Tiered retrieval

Do not put the full catalog into one prompt.

```text
BU or Cross-BU path
→ feature group
→ approved individual features
```

Use generated Vietnamese descriptions and synonyms.

### Ratio features

Prefer approved precomputed ratio features. Do not replace them with ad-hoc
division unless no approved ratio exists and the aggregation semantics explicitly
allow derivation.

---

## 8. Cross-BU rules

Prefer:

```text
feature.customer_cross_bu_feature
```

Do not manually join GSM and VinFast when the bridge already contains the required
concept.

All join paths must exist in `metadata.join_catalog`.

Reject:

- joins outside the catalog;
- joins missing required keys;
- Cartesian joins;
- unsupported three-table joins;
- joins to raw or restricted tables.

Snapshot feature joins require:

```sql
left.customer_id = right.customer_id
AND left.snapshot_date = right.snapshot_date
```

Joining only on `customer_id` is prohibited because it can silently multiply rows.

Cross-BU questions must also handle:

- one-sided customers without losing them through an inner join;
- explicit denominator for averages;
- mismatched time windows;
- missing time windows;
- null versus zero semantics.

---

## 9. Buyer, owner, and point-in-time

```text
Vehicle buyer:
customer satisfying the approved completed-purchase definition.

Vehicle owner:
customer with completed handover evidence as of the requested snapshot.
```

Rules:

- Completed order is not ownership.
- Scheduled handover is not ownership.
- Completed handover requires `handed_over_at`.
- Buyer=true and owner=false is a valid population.
- “Total vehicles delivered” counts vehicles, not customers.
- “Total / from the beginning” uses `_all`, not `_l1m`.
- “Last month” uses the historical snapshot.
- Future handover must not leak into earlier snapshots.
- Returned/reversed handover is unsupported unless an approved feature represents
  it.
- Never answer “returned vehicle” using `NOT is_vehicle_owner`.

For snapshot `D`, only approved events with `event_time <= D` may contribute.

PIT correctness is a hard requirement.

---

## 10. Short-term conversational state

The project does not use long-term memory.

At most one pending clarification exists per session.

```text
session_id
original_question
parsed_intent
known_slots
missing_slots
clarification_question
created_at
expires_at
```

Required behavior:

- `GSM`, `VF`, and `VinFast` may resolve a missing BU.
- `cả hai` routes to Cross-BU when the pending intent supports it.
- A complete new question replaces the old pending question.
- A short new question with a changed metric must not be attached to the old
  intent.
- Expired state is not revived.
- State does not leak across sessions.
- State is deleted after resolve or cancel.

Current prototype debt:

- `_STORE` is process-local.
- State is lost on restart.
- State is not shared across workers.
- No thread/process locking.
- The heuristic may confuse a short new question with a slot answer.

Accepted examples:

```text
"GSM"                  → resolve pending BU
"Cho GSM nhé"          → resolve pending BU
"Doanh thu GSM?"       → replace pending question
"Top 10 khách VinFast" → replace pending question
```

Move to Redis before multi-worker or production deployment. Tune the heuristic
with a tagged golden set.

---

## 11. SQL guardrails

Guardrails are enforced below the prompt.

Allowed:

- one statement;
- `SELECT` or approved `WITH ... SELECT`;
- read-only execution;
- configured row limit and timeout.

Blocked:

- DDL and DML;
- multi-statement SQL;
- `SELECT *`;
- raw tables;
- PII and restricted columns;
- joins outside `join_catalog`;
- joins missing snapshot keys;
- Cartesian joins;
- search-path manipulation;
- prompt-based policy bypass.

The validator must inspect all AST references, including CTEs and subqueries.

Execution-error repair is limited to two attempts. Every repair passes the full
validator again. A policy rejection is final and must not enter the repair loop.

---

## 12. Response and UI

All user-facing output is Vietnamese.

Successful answers show:

- concise result;
- KPI card, table, or supported chart;
- generated SQL;
- confidence;
- coverage warning;
- join explanation for Cross-BU.

Current result shapes:

- scalar → KPI card;
- time series → line chart;
- ranking/detail → table.

Sparse coverage must be visible. Show covered rows, eligible population when known,
coverage percentage, and a configurable warning. Do not hardcode thresholds.

---

## 13. Evaluation

Evaluate generated SQL by executing gold and generated SQL on the same
deterministic dataset and comparing result sets, not SQL strings.

Required groups:

- Sprint 1 regression;
- Cross-BU;
- buyer versus owner;
- point-in-time;
- multi-turn;
- new-question replacement;
- join safety;
- raw/PII safety;
- out-of-scope;
- result shape;
- hard Vietnamese business phrasing.

Sprint 2 target metrics:

| Metric | Target |
|---|---:|
| Cross-BU table selection | ≥ 90% |
| Join-plan accuracy | ≥ 90% |
| PIT correctness | 100% |
| Buyer/owner accuracy | 100% |
| Multi-turn resolution | ≥ 95% |
| State isolation | 100% |
| SQL executable rate | ≥ 90% |
| Result accuracy | ≥ 85% |
| Safety rejection | 100% |
| Visualization selection | ≥ 85% |
| Raw/PII successful access | 0 |

Do not claim targets were achieved unless the evaluation report exists.

Never tune on holdout. Lock catalog, retriever, prompt, model, join planner, and
validator versions before the release holdout run.

---

## 14. Mock and test data

Generate raw-like events, then derive approved features. Do not randomize feature
columns independently.

Inputs:

- customers;
- GSM trips;
- VinFast orders;
- order status history;
- vehicle handover.

Outputs:

- `feature.gsm_transaction`;
- `feature.vinfast_transaction`;
- `feature.customer_cross_bu_feature`.

Use a fixed seed and include:

- GSM increase/decrease;
- VinFast order spike;
- completed order without handover;
- future handover after an earlier snapshot;
- GSM-only, VinFast-only, and both-BU customers;
- genuine nulls;
- buyer=true and owner=false.

Required invariants include no future leakage, no Cross-BU row multiplication, and
buyer/owner populations not being identical.

---

## 15. Next build order: Sprint 3

The next major workstream is the proactive reporter.

1. Snapshot registry and freshness checks.
2. Approved KPI catalog.
3. Deterministic nightly scanner.
4. KPI observations with lineage.
5. Rule-based anomaly detection.
6. Statistical anomaly detection with minimum history.
7. Insight prioritization and deduplication.
8. Evidence-only Vietnamese Story Generator.
9. Factuality checking.
10. Scheduled report rendering and delivery.
11. Idempotency, retry, monitoring, and runbooks.
12. Sprint 3 benchmark and release evaluation.

```text
snapshot readiness
→ KPI catalog
→ deterministic observations
→ anomaly detection
→ prioritization
→ validated evidence
→ Vietnamese story
→ factuality check
→ idempotent delivery
```

Reporter hard rules:

- The LLM never scans raw data.
- The LLM does not decide what is anomalous.
- The LLM narrates precomputed evidence only.
- Every number maps to evidence.
- No unsupported causal claims.
- Retry must not create duplicate reports.

---

## 16. Out of scope

- `global_loyalty` and loyalty-led Cross-PnL.
- Business Units other than GSM and VinFast.
- Global company aggregate feature layer.
- Feature curation and approval.
- Direct raw analysis by the query Agent.
- Long-term memory.
- Redis in the current prototype.
- Automatic semantic promotion.
- Causal inference.
- Forecasting unless separately approved.
- Returned-vehicle or ownership-transfer semantics without approved features.
- Arbitrary user-triggered write actions.
- dbt and Cube unless reopened through an ADR.

The proactive reporter may publish approved scheduled reports through configured
delivery adapters. This does not grant the query Agent arbitrary action-taking
capability.

---

## 17. Rules for Claude Code

Apply the general coding behavior in Section 2 and the project-specific rules
below. When they conflict, the stricter project rule wins.

Before writing code:

1. Read this file fully.
2. Read the relevant contract and ADR.
3. Inspect the physical schema, current implementation, and tests.
4. Check whether the requested behavior already exists.
5. State material assumptions and ambiguities before implementation.
6. For non-trivial work, provide a brief plan with a verification check for each
   step.
7. Run the smallest relevant test group before changing code.
8. Define success criteria before implementation.
9. Make the smallest change that satisfies the request.
10. Do not silently change semantics.
11. Do not refactor, reformat, or clean unrelated code.
12. Remove only unused code introduced by your own change.
13. A new table, feature, join, or business definition requires updates to:
    - schema;
    - YAML;
    - catalog deployment;
    - tests;
    - golden set;
    - documentation.
14. Do not weaken a guard to make a test pass.
15. Do not bypass `join_catalog`.
16. Do not access `raw.*` from the user-facing Agent.
17. Do not map buyer to owner.
18. Do not use current state for historical answers.
19. Do not hardcode credentials, DB URLs, TTLs, thresholds, limits, or channel IDs.
20. Preserve Vietnamese user-facing output.
21. Record before/after evaluation numbers for prompt, retrieval, semantic, join,
    or guard changes.
22. Verify the requested outcome with tests, evaluation, or a reproducible command
    before declaring the work complete.

When repository reality conflicts with this file:

- do not guess;
- name the conflict;
- identify the schema, contract, ADR, test, or evaluation artifact that should be
  treated as authoritative;
- ask before changing behavior when the authority is unclear.

These guidelines are working when diffs stay small, requested behavior is
verifiable, and clarifying questions happen before incorrect implementation.
