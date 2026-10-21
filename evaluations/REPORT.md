# Synthetic NLP and planning regression benchmark

Measured on Python 3.12 with SQLite, persistent LangGraph checkpoints and the offline rules parser. Both hash features and actual checksum-verified ONNX all-MiniLM-L6-v2 weights were evaluated on the same corpus. No paid LLM calls were made.

## Correctness and conversation

- With Gemini provider support added, 72 tests pass independently on SQLite and PostgreSQL with actual MiniLM integration enabled. Gemini extraction itself is tested with simulated model responses; no live Gemini key is configured. Normal test runs skip the opt-in real-weight test.
- Opt-in actual MiniLM tests passed, including a semantic paraphrase similarity check and real Chroma retrieval.
- 20 randomized tiny networks matched an independent exhaustive oracle for both objectives.
- 100/100 planning fixtures matched expected fields and final statuses; 110 returned routes passed independent verification.
- 16/16 manually specified NLP paraphrases matched the full extracted patch and the expected clarification decision. These exercise spelled numbers, currency, synonyms, preferences, ambiguous dates and missing context.
- A real API two-turn revision preserved the $4,000 ceiling and correctly reported a $1,300 difference from the previous verified recommendation.
- Browser checks cover revisions, comparisons, suggestion application, clarification, reload persistence and mobile layout.

## Retrieval

60 labeled queries; five similar source sections per carrier are all considered relevant. Recall@5 divides relevant hits by the full gold set. MRR uses first relevant rank; nDCG uses binary relevance.

| Embeddings | Ranking | Recall@5 | MRR | nDCG@5 |
|---|---|---:|---:|---:|
| hash | dense | 0.9233 | 0.9267 | 0.9210 |
| hash | bm25 | 0.9667 | 0.9667 | 0.9667 |
| hash | hybrid | 0.9400 | 0.9833 | 0.9499 |
| hash | reranked | 0.9367 | 0.9667 | 0.9436 |
| minilm | dense | 0.9500 | 0.9500 | 0.9479 |
| minilm | bm25 | 0.9667 | 0.9667 | 0.9667 |
| minilm | hybrid | 0.9633 | 0.9667 | 0.9617 |
| minilm | reranked | 0.9467 | 0.9500 | 0.9464 |

Learned hybrid recall improved on this fixture, but BM25 still has slightly higher recall on the name-heavy corpus. Token-coverage reranking did not improve recall; it is not a cross-encoder. These results do not establish that one retrieval method is universally better.

## Latency

| Embeddings | Workflow P50 / P95 (ms) | ASGI HTTP P50 / P95 (ms) |
|---|---:|---:|
| hash | 48.43 / 84.15 | 122.58 / 195.19 |
| minilm | 85.08 / 137.71 | 156.9 / 191.28 |

Workflow latency spans 100 fixtures; HTTP latency uses 12 in-process ASGI samples with SQL persistence, excluding real network transport and any LLM latency. The host was shared with validation/build work; these are illustrative timings, not isolated performance measurements.

## Limits and reproduction

The fixtures are synthetic regressions, not held-out human-labeled production data. Repeated profile sections and carrier-name queries make retrieval optimistic. Exact-patch matching is not entity F1. Live LLM quality, Ragas, human grounding review, token cost, real freight eligibility and production latency are unmeasured. Pharmaceutical certification and numeric temperature ranges are not modeled.

Run `EMBEDDING_BACKEND=hash .venv/bin/python -m evaluations.run`, then `EMBEDDING_BACKEND=minilm .venv/bin/python -m evaluations.run`. Results are retained separately in `results-hash.json` and `results-minilm.json`; `results.json` is the most recent run. Labels are in `planning_requests.json`, `nlp_queries.json`, and `retrieval_queries.json`. For the real model test run `RUN_SEMANTIC_TESTS=1 .venv/bin/pytest tests/test_semantic.py -q`.
