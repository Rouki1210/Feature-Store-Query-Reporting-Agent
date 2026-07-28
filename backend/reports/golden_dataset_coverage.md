# Golden dataset coverage (Task 1.4)

- Tổng: **86** case — dev **57**, holdout **29** (disjoint).
- Holdout checksum: `1033c4b8755f917f...`
- Cross-BU trong benchmark: **9** ['G13', 'S02', 'S03', 'S06', 'S15', 'S16', 'S17', 'S18', 'S19']

## Theo độ khó (dev / holdout)

| difficulty | dev | holdout |
|---|---:|---:|
| easy | 16 | 6 |
| medium | 28 | 13 |
| hard | 13 | 10 |

## Theo category (mục đích) (dev / holdout)

| category | dev | holdout |
|---|---:|---:|
| ambiguous_question | 3 | 1 |
| buyer_vs_owner | 5 | 2 |
| cross_bu | 3 | 5 |
| join_safety | 2 | 0 |
| out_of_scope | 7 | 3 |
| point_in_time | 1 | 2 |
| restricted_data | 3 | 1 |
| service_breakdown | 3 | 3 |
| single_feature | 24 | 11 |
| sql_safety | 3 | 0 |
| time_comparison | 3 | 1 |

## Theo Business Unit (toàn tập)

| BU | count |
|---|---:|
| GSM | 26 |
| VINFAST | 29 |
| (guardrail/none) | 22 |
| CROSS_BU | 9 |
