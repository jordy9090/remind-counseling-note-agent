# Retrieval Evaluation Report

Synthetic evaluation only. No real counseling records or remote database rows are used.
Evaluation set: 29 Korean queries across KB, case memory, and negative leakage scenarios.

| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | Category Accuracy | Source Ref Validity | Cross-Case Leakage | Embedding Mean ms | RPC Mean ms | Total Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| recency_only | 0.17 | 0.17 | 0.17 | 0.17 | 0.00 | 1.00 | 0 | 0.000 | 4.262 | 4.662 |
| dense_only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 | 14.500 | 3.831 | 18.731 |
| lexical_only | 0.86 | 0.86 | 0.86 | 0.86 | 0.96 | 1.00 | 0 | 0.000 | 3.834 | 4.234 |
| hybrid | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 | 14.438 | 3.803 | 18.641 |

Latency values are synthetic phase timings for the mock evaluator. Remote checks report measured embedding and Supabase RPC timings separately.
The pg_trgm lexical fallback is included in the SQL migration, but real lexical quality must be judged from remote seeded KB queries.
Do not claim production retrieval quality from this synthetic report.
