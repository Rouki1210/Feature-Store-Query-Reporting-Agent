=== EVAL REPORT  tag=sprint1_final  split=dev  model=levuphong2909/gpt-5.6-sol  LLM=on ===
  holdout: dev split (holdout không dùng)

[Theo độ khó]
  nhóm                    retrieval      refusal     exec_acc    gold_ok
  easy                   8/8 (100%)   5/5 (100%)     0/8 (0%) 8/8 (100%)
  hard                    6/7 (85%)          n/a     0/7 (0%) 7/7 (100%)
  medium                13/15 (86%)   5/5 (100%)    0/15 (0%) 15/15 (100%)

[Theo category (mục đích)]
  nhóm                    retrieval      refusal     exec_acc    gold_ok
  ambiguous_question            n/a   1/1 (100%)          n/a        n/a
  out_of_scope                  n/a   6/6 (100%)          n/a        n/a
  restricted_data               n/a   1/1 (100%)          n/a        n/a
  service_breakdown      3/3 (100%)          n/a     0/3 (0%) 3/3 (100%)
  single_feature        22/24 (91%)          n/a    0/24 (0%) 24/24 (100%)
  sql_safety                    n/a   2/2 (100%)          n/a        n/a
  time_comparison         2/3 (66%)          n/a     0/3 (0%) 3/3 (100%)

[Recall@5]
  difficulty: easy=100%, hard=86%, medium=87%
  category: ambiguous_question=  n/a, out_of_scope=  n/a, restricted_data=  n/a, service_breakdown=100%, single_feature=92%, sql_safety=  n/a, time_comparison=67%

[Overall]
  retrieval_hit@5 : 27/30 (90%)
  retrieval_recall@5: 90%
  refusal_accuracy: 10/10 (100%)
  execution_acc   : 0/30 (0%)
  gold_sql_ok     : 30/30 (100%)
  latency p50/p95 : 10514ms / 14333ms
  skipped (needs LLM): 0

[Dataset health]
  gold_sql_execution_rate       : 100%
  expected_result_available_rate: 100%

[Retrieval]
  retrieval_hit@1               : 60%
  retrieval_hit@3               : 83%
  retrieval_hit@5               : 90%
  MRR                           : 0.728
  selected_context_accuracy     : 0%

[SQL generation]
  SQL present                    : 28/30 (93%)
  Parse success | SQL present    : 28/28 (100%)
  Schema valid | parsed          : 28/28 (100%)
  Execution success | valid      : 0/28 (0%)
  Result match | executed        : n/a

[End-to-end]
  result_match_accuracy         : 0%
  task_success_rate             : 25%

[Clarification / refusal]
  clarification_precision       : 50%
  clarification_recall          : 100%
  refusal_precision             : 100%
  refusal_recall                : 100%
  over_refusal_rate             : 0%

[Performance]
  latency_p50                   : 10514ms
  latency_p95                   : 14333ms
  retrieval_latency_p95         : 19ms
  llm_latency_p95               : 14296ms
  sql_latency_p95               : 8ms