# Synthetic regression benchmark

Measured on Python 3.12 with SQLite, persistent LangGraph checkpoints and the offline rules parser. The default Chroma embedding model is `normalized-feature-hash-v1-384`. No live LLM or downloaded semantic model was used.

## Planning and correctness

- 46 automated tests passed against SQLite and PostgreSQL independently.
- The optimizer matched an independent cartesian exhaustive oracle on 20 randomized tiny networks for both objectives.
- 100/100 templated requests matched expected extracted fields and final status.
- 50 requests completed; all 110 returned routes passed independent authoritative verification.
- Browser smoke checks passed for cheapest, fastest, clarification, reload persistence, no-route and mobile layout.

Direct workflow latency: P50 29.76 ms, P95 35.83 ms.
In-process ASGI HTTP samples (n=12): P50 36.79 ms, P95 42.58 ms. This includes SQL persistence but excludes real network transport and LLM latency.

## Retrieval

60 queries with gold source IDs. Each carrier has five similar profile sections, all counted as relevant. Recall@5 uses the full gold set; MRR uses first relevant hit; nDCG uses binary relevance.

| Mode | Recall@5 | MRR | nDCG@5 |
|---|---:|---:|---:|
| dense | 0.9233 | 0.9267 | 0.9210 |
| bm25 | 0.9667 | 0.9667 | 0.9667 |
| hybrid | 0.9400 | 0.9833 | 0.9499 |
| reranked | 0.9367 | 0.9667 | 0.9436 |

Dense here means cosine similarity on normalized hash features, not learned semantic embeddings. Hybrid is BM25 plus dense reciprocal-rank fusion (constant 60). Reranking uses token coverage over the top 15 hybrid hits, not a cross-encoder. BM25 performed best on this corpus by recall; the experiment does not show hybrid or reranking universally improves quality.

## Limits and reproducibility

The datasets are synthetic template regressions, not held-out human labels. Repeated profile sections and carrier-name queries make retrieval optimistic. Parser expected-field matching is not entity F1; no claim is made about arbitrary-language accuracy, Ragas scores, human citation review, LLM token cost or production latency. Misleading-evidence tests verify that SQL eligibility and numerical results cannot be overridden by prose.

Run `.venv/bin/python -m evaluations.run` from the repository root to refresh `results.json`. The labeled inputs are `planning_requests.json` and `retrieval_queries.json`. Times vary by machine. Test suite: `.venv/bin/pytest -q`.
