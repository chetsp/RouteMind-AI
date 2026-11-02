# NLP and policy quality evaluation

This suite adds entity precision/recall/F1 and policy-quality evaluation to the existing routing and retrieval regressions. It does not replace `evaluations/run.py` or claim production accuracy.

## Frozen cases and splits

`cases.json` contains 64 synthetic NLP cases (32 development, 32 test) and 50 policy questions (25 development, 25 test). NLP groups are directed origin/destination pairs; policy groups are carrier IDs. No group crosses the split boundary. The report includes the dataset SHA256 and per-case predictions so changes can be audited.

Labels are authored synthetic expectations built with shared question templates, not independent human annotations. Geography and language patterns overlap, and test labels are public in the repository. This is a reproducible group holdout, not a blinded or production test. Use development cases for changes; treat test results as a final check. A later dataset should use independently written requests and expert labels, with more varied linguistic and policy cases.

## Run without hosted model calls

From the repository root:

```bash
.venv/bin/python -m evaluations.quality.run --split dev --backend hash
.venv/bin/python -m evaluations.quality.run --split test --backend hash
.venv/bin/python -m evaluations.quality.run --split dev --backend minilm
.venv/bin/python -m evaluations.quality.run --split test --backend minilm
```

The runner uses a disposable SQLite database and Chroma index. Model weights use the existing cache. It never writes evaluation requests into your normal database. Offline mode does not call Gemini/OpenAI, even if credentials are configured. MiniLM mode requires cached weights or download access.

Reports contain full examples, original passages, exclusions and editable human-review fields. `--output /tmp/my-report.json` chooses a destination. `--limit 3` runs three cases per dataset and labels the result partial; partial reports are not comparable to full reports.

## Optional live-model evaluation

Use the existing Gemini/OpenAI environment configuration. This must be explicitly enabled:

```bash
.venv/bin/python -m evaluations.quality.run --split dev --backend minilm --live-model --limit 3 --output /tmp/live-quality-sample.json
```

Hosted calls may incur charges. A full split evaluates 32 extraction requests and up to 25 policy questions; the evidence gate may skip policy calls. The runner records the configured model but never keys. Policy-model failures are reported separately, not scored as successful abstention. Extraction failures incur missing-entity errors and are counted explicitly. No live calls were made for the committed reports.

## Metrics and interpretation

- **NLP micro precision/recall/F1:** one entity per scalar field/value or capability member. A wrong value incurs a false positive and false negative; extra fields are penalized. Per-field results and clarification-decision accuracy are included. Offline results evaluate rules, not an LLM.
- **Answerable retrieval recall:** fraction of labelled relevant source IDs present in the actual response evidence after review and context limits. Here each positive question has five near-duplicate carrier passages as gold, which makes the benchmark unusually easy. This metric is not Recall@5.
- **Relevance-gate accuracy proxy:** whether the gate passes an answerable question or rejects an unanswerable one. A relevant passage does not necessarily answer a question; this proxy is deliberately labelled and must not be mistaken for answer accuracy.
- **Live citation precision:** selected source IDs present in the labelled gold set divided by all selected IDs. `unsupported_source_selections` counts IDs outside gold. These are source-selection proxies, not proof of semantic faithfulness or an unsupported factual-claim rate.
- **Live unanswerable abstention accuracy:** no findings for labelled unanswerable questions. Gate abstentions count as pipeline abstentions; model failures do not.
- **Human grounding:** unmeasured until a reviewer fills each sample's `human_review` fields for relevance, completeness and unsupported claims. No Ragas score is fabricated.

## Measured offline results

| Split | Embeddings | Rules entity F1 | Clarification accuracy | Answerable retrieval recall | Relevance-gate proxy |
|---|---|---:|---:|---:|---:|
| Development | Hash | 1.00 | 1.00 | 0.90 | 0.96 |
| Development | MiniLM | 1.00 | 1.00 | 0.90 | 0.88 |
| Test | Hash | 1.00 | 1.00 | 0.90 | 0.96 |
| Test | MiniLM | 1.00 | 1.00 | 0.90 | 0.96 |

Perfect extraction on repeated synthetic templates does not establish general language understanding. The development MiniLM result also shows that a learned similarity score can admit irrelevant passages. The gate is conservative screening, not a completeness guarantee; thresholds have not been statistically calibrated. Hosted model answer quality, human grounding and operational impact remain unmeasured.

Adversarial coverage for expired/future/superseded documents, reviewed-claim conflicts, SQL disagreements, fabricated citations and SQL-only route planning lives in `tests/test_evidence.py` and `tests/test_policies.py`.

## Ragas, paired parser comparison and reviewer study

See [the evaluation workflow](REVIEW_GUIDE.md) for optional Ragas faithfulness/context-precision/answer-relevance judging, a paired rules-versus-LLM parser comparison, and two independent 10-case review packs with 5 shared cases. Ragas uses a separate pinned environment. Paid calls require explicit flags; actual human ratings are never generated automatically. These tools do not change the earlier offline scores or establish completed live/human evaluation.
