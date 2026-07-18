# Retrieval Evaluation Report

Synthetic evaluation only. No real counseling records or remote database rows are used.

| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | Category Accuracy | Cross-Case Leakage | Mean Latency ms | p95 Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| recency_only | 0.40 | 0.40 | 0.40 | 0.40 | 0.00 | 0 | 0.001 | 0.003 |
| dense_only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 | 0.000 | 0.001 |
| lexical_only | 0.70 | 0.70 | 0.70 | 0.70 | 1.00 | 0 | 0.001 | 0.001 |
| hybrid | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 | 0.000 | 0.001 |

The pg_trgm lexical fallback is included in the SQL migration, but real lexical quality must be judged from remote query results after KB seeding.
Do not claim production retrieval improvement from this synthetic mock report alone.
