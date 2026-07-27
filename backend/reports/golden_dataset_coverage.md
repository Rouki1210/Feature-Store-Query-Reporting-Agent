# Golden dataset coverage (Task 1.4)

- Tổng: **60** case — dev **40**, holdout **20** (disjoint).
- Holdout checksum: `71c1c81cec7f0537...`
- Cross-BU trong benchmark: **0** (OK)

## Theo độ khó (dev / holdout)

| difficulty | dev | holdout |
|---|---:|---:|
| easy | 13 | 6 |
| medium | 20 | 11 |
| hard | 7 | 3 |

## Theo category (mục đích) (dev / holdout)

| category | dev | holdout |
|---|---:|---:|
| ambiguous_question | 1 | 1 |
| out_of_scope | 6 | 3 |
| restricted_data | 1 | 1 |
| service_breakdown | 3 | 3 |
| single_feature | 24 | 11 |
| sql_safety | 2 | 0 |
| time_comparison | 3 | 1 |

## Theo Business Unit (toàn tập)

| BU | count |
|---|---:|
| GSM | 26 |
| VINFAST | 19 |
| (guardrail/none) | 15 |
