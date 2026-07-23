# CLAUDE.md

Guidance for Claude Code working in this repository. Read fully before writing code.

---

## 1. What this project is

**Feature Store Query & Reporting Agent** — a BI agent over a corporate feature
store, with two modes:

1. **On-demand analyst** — non-technical staff ask questions **in Vietnamese**;
   the agent selects the right features, generates SQL, returns a table or simple
   chart.
2. **Proactive reporter** — a nightly job that statistically detects notable
   shifts (especially *cross-business-unit* shifts) and publishes a plain-Vietnamese
   executive summary to a team channel.

**Critical boundary:** the agent **consumes** approved features. It does **not**
manage, evaluate, or curate them — feature curation is a separate human process
upstream and is out of scope.

**Primary users:** PnL product/business managers (ask in Vietnamese, use business
vocabulary, never feature names) and executives (consumers of the nightly report).
**Secondary:** data analysts who verify generated SQL and maintain the agent.

---

## 2. Data scope (fixed for now)

Three tables, **652 approved features** derived from **120 base metrics**:

| Table | Unit | Features | Base stems | Role |
|---|---|---|---|---|
| `gsm_transaction` | GSM | 167 | 28 | Ride/delivery transactions |
| `vinfast_transaction` | VinFast | 186 | 34 | Vehicle & accessory orders |
| `global_loyalty` | Global | 299 | 58 | **Cross-PnL bridge** |

`gsm_event` (187 features) is deliberately deferred — behavioural event data,
not needed for the core use cases.

### Why `global_loyalty` is the centre of gravity

It holds 224 features shaped `global_loyalty_pnl_{pnl}_{earn|burn}_completed_{pts_sum|txn_count}_{window}`
across **11 PnLs** (gsm, vinfast, vinhomes, vinmec, vinpearl, vinschool, vinclub,
vincomretail, merchant, vapp, fgf). GSM and VinFast each have a complete,
symmetric set of 20.

This means: points a customer **earns at GSM** and **burns at VinFast** sit in the
same table under the same customer. That is what makes *cross-unit* questions
answerable — the differentiating capability of this project. Prioritise it.

Also present: `global_loyalty_primary_earn_pnl_{l6m,l12m}` and
`primary_burn_pnl_{l6m,l12m}` (dominant PnL per customer).
**Constraint:** these exist ONLY at l6m/l12m — there is no l1m. For
short-window "where are they spending now" questions, derive it by comparing the
11 `pnl_*` columns instead.

### Feature name grammar

Names follow `{table}_{filter}_{metric}_{aggregation}_{window}`. Windows:
`daily`, `l1w`, `l2w`, `l1m`, `l3m`, `l6m`, `l12m`, plus 57 ratio features
(`l1m_vs_l3m`, `l1m_vs_l6m`, `l1m_vs_l12m`, `l3m_vs_l12m`).

**Ratio features are pre-computed — always prefer them over dividing two columns
in generated SQL.** The ratio definition is already standardised; ad-hoc division
introduces zero-denominator and window-mismatch bugs.

---

## 3. The semantic layer (already solved — do not redo by hand)

`feature_describer.py` parses feature names into components and generates
Vietnamese descriptions + Vietnamese search keywords. It covers all 472
in-scope features with **zero unparsed tokens**.

This exists because the source descriptions were unusable: all `_pnl_*` features
shared one template string ("Monthly PNL completed earn points; {pnl}=fgf,gsm,...")
that distinguished neither PnL nor window — an LLM reading it cannot pick the
right column.

Rules:
- **Never hand-write feature descriptions.** Extend the dictionaries in
  `feature_describer.py` (`METRICS`, `SEGMENTS`, `STATUS`, `SYNONYMS`) and
  regenerate. One dictionary entry fixes every feature that uses that token.
- `SYNONYMS` (Vietnamese business vocabulary) is the one layer that cannot be
  derived from names. It is the highest-value thing to grow — real user questions
  say "khách sắp rời bỏ", never `days_since_last_txn`.
- Two tokens are unverified guesses needing human confirmation: `wo`
  (assumed "work order") and `nvso` (meaning unknown). Flag, don't invent.

---

## 4. Architecture

```
Vietnamese question
  → intent router          (cross-PnL question? → dedicated path)
  → tiered feature retrieval  table → feature group → specific features
  → SQL generation         (LLM, with retrieved features only)
  → guarded execution      (read-only, row limit, sensitive-column deny)
  → self-correction loop   (max 2 repairs on execution error)
  → table / chart + the SQL shown for verification
```

Nightly:
```
statistical scan (pandas, deterministic)
  → cross-PnL flow signals + within-PnL anomalies
  → LLM narrates PRE-COMPUTED findings only
  → publish to team channel (Vietnamese)
```

### Tiered retrieval is mandatory

652 features cannot fit in one prompt. Retrieval must narrow in stages:
table → feature group (7 groups already exist in the source data: "Giá trị & số
dư", "Hành trình & trạng thái", "Thời gian & gắn kết", "Tỷ lệ & xu hướng",
"Kênh & ngữ cảnh", "Sản phẩm & dịch vụ", "Hoạt động & tần suất") → individual
features. Use the generated Vietnamese keywords for matching.

---

## 5. Non-negotiable rules

- **Read-only, enforced below the prompt.** Only `SELECT`/`WITH` pass the guard;
  every query gets a hard row limit. Prompt-level exclusion of sensitive columns
  is necessary but NOT sufficient — `SELECT *` and explicitly-named columns must
  be blocked at execution and, where DB privileges allow, by column-level GRANT.
- **The LLM never reads raw data in the reporter.** Statistics decide what is
  notable; the LLM only rewrites validated findings. This makes fabricated
  numbers structurally impossible.
- **Always show the generated SQL.** Users cannot verify results otherwise.
- **Flag low-confidence answers.** Many features are sparsely populated. Returning
  an average computed over 15% of customers without saying so is misleading even
  when the SQL is perfect. Surface the coverage.
- **The agent must be able to say "I'm not sure."** Ambiguous question → ask back.
  Outside the data → say so. Never guess.
- **Config only** — no hardcoded credentials, thresholds, or DB URLs.
- **Vietnamese output.** Descriptions, summaries, and error messages face
  non-technical Vietnamese-speaking users.

---

## 6. Build order (base first)

1. **Config + DB connection** (SQLAlchemy; Postgres target, engine-agnostic).
2. **Semantic layer loader** — read `semantic_layer.yaml`, expose
   `retrieve(question) -> feature context`. Start with keyword matching over the
   generated Vietnamese keywords; upgrade later if measurements justify it.
3. **SQL guards** (`SELECT`-only, row limit, sensitive-column deny-list) **+ tests
   before anything calls an LLM.**
4. **Mock data generator** — see section 7. Needed before any evaluation is
   meaningful.
5. **SQL generation + self-correction loop.**
6. **Evaluator** — execution accuracy on a tagged golden set (see section 8).
7. Only then: chat UI, then the nightly reporter.

---

## 7. Mock data — generate raw events, then aggregate

Real warehouse access is not yet available, and the raw source schema is unknown.
Generate mock data in **three layers**; do NOT generate feature columns directly
with random values.

1. **Raw events** (~15 months, to fill the l12m window): `customers`,
   `gsm_trips` (service type taxi/bike/express/food, original price, discount,
   distance_km, status, timestamp), `vinfast_orders` (accessories vs vehicle vs
   work-order, price, amount, status, processing time), `loyalty_ledger`
   (customer, **pnl**, earn/burn, points, status, timestamp).
2. **Derive features** from layer 1 by actual aggregation.
3. **Plant known stories** for testing: a segment shifting GSM→VinFast burn; a
   month-over-month spike; customers with genuine nulls (never bought VinFast).

Why: generating each feature column independently produces contradictory data
(`l1m` > `l3m`, ratios not matching their components). Evaluation on inconsistent
data is worthless. Deriving from raw events guarantees internal consistency.
Use a fixed seed — reproducibility is required for accuracy measurement.

---

## 8. Quality measurement

Execution accuracy over a golden set: run gold SQL and generated SQL, compare
result sets order- and column-name-insensitively.

The golden set **must include a tagged "hard" group** that cannot be solved by
matching column names: Vietnamese phrasing, business vocabulary differing from
feature names, ambiguous questions, cross-PnL questions. Report accuracy per
group — an overall number hides where the semantic layer actually earns its keep.

Run the evaluator before and after every prompt or semantic-layer change, and
record both numbers.

---

## 9. Out of scope

- The other 11 tables (Vinhomes, Vinmec, Vinpearl, VinClub, VinSchool, VinUni,
  VCR) — expand only after the architecture is proven on three.
- Feature curation / keep-drop decisions — a separate human process.
- Agent taking actions (sending email, writing data) — read-only by design.
- dbt / Cube — considered and deferred; record as an ADR if revisited.

---

## 10. Open questions for the human

1. **Row grain** — features are per-customer. Does the table carry a snapshot
   date (enabling time-series comparison for the nightly reporter), or only the
   latest state? This determines whether cross-PnL *shift* detection is possible.
2. **DB privileges** — is column-level `GRANT` (or sanitized views) available?
   Determines whether sensitive-column control can be enforced properly.
3. **`wo` and `nvso`** — confirm meanings so descriptions can be corrected.
