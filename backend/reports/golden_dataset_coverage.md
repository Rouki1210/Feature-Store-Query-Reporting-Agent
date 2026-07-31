# Golden dataset coverage (Task 1.4)

- Tổng: **100** case — dev **70**, holdout **30** (disjoint).
- Holdout checksum: `d84a225500f0d4df...`
- Cross-BU trong benchmark: **12** ['G13', 'S02', 'S03', 'S06', 'S15', 'S16', 'S17', 'S18', 'S19', 'V01', 'V02', 'V04']

## Theo độ khó (dev / holdout)

| difficulty | dev | holdout |
|---|---:|---:|
| easy | 16 | 6 |
| medium | 37 | 10 |
| hard | 17 | 14 |

## Theo category (mục đích) (dev / holdout)

| category | dev | holdout |
|---|---:|---:|
| ambiguous_question | 3 | 1 |
| buyer_vs_owner | 5 | 1 |
| cross_bu | 3 | 5 |
| insufficient_data | 2 | 0 |
| join_safety | 2 | 0 |
| out_of_scope | 5 | 1 |
| point_in_time | 2 | 1 |
| restricted_data | 4 | 1 |
| semantic_clarification | 1 | 1 |
| service_breakdown | 3 | 3 |
| short_term_state | 8 | 2 |
| single_feature | 25 | 10 |
| sql_safety | 2 | 1 |
| time_comparison | 3 | 1 |
| visualization | 2 | 2 |

## Theo Business Unit (toàn tập)

| BU | count |
|---|---:|
| GSM | 31 |
| VINFAST | 35 |
| (guardrail/none) | 22 |
| CROSS_BU | 12 |
