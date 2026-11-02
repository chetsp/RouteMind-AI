# Three-part evaluation: model judge, paired parsing and independent reviewers

The original near-perfect scores are synthetic regression results. This workflow adds evaluation instruments; it does not claim that live-model judging or human review has already been performed. It keeps the existing frozen cases unchanged. Use the development split while improving the implementation and reserve the test split for the final check.

## 1. Compare rules and an LLM on identical requests

From the repository root, with the normal application environment installed:

```bash
.venv/bin/python -m evaluations.quality.compare_parsers --split dev --output evaluations/review-runs/parser-offline.json
```

This measures rules only. The model column and paired differences remain null. To enable real calls, configure the existing `ROUTEMIND_PROVIDER`, `ROUTEMIND_MODEL` and provider-specific key locally, then run:

```bash
.venv/bin/python -m evaluations.quality.compare_parsers --split dev --live-model --limit 10 --output evaluations/review-runs/parser-paired.json
```

Evaluation commands do not automatically load `.env`. Export the values first; do not paste keys into reports or chat. Calls may incur charges. Both parsers receive the same text, hub directory and gold fields. The comparison reports micro entity precision/recall/F1, exact field accuracy, clarification accuracy, failures, median serial latency and paired differences. There is no fallback that disguises a failed model call as successful rules output. A failed call receives no clarification credit. `--limit` is marked partial; do not compare it to a full run.

A model may perform worse or cost more on these simple templates. That is a valid result, not a reason to change the labels or hide failures. This comparison still does not establish performance on independently written requests.

## 2. Capture policy outcomes, then use Ragas

Produce an actual live response file using the existing quality runner:

```bash
.venv/bin/python -m evaluations.quality.run --split dev --backend minilm --live-model --output evaluations/review-runs/policy-live.json
```

A full split makes 32 extraction calls and up to 25 policy-reading calls. Gates can skip policy calls. This existing runner produces both datasets; parser comparison above provides the paired view. MiniLM needs cached weights or download access. Do not substitute fixture or offline retrieval responses and describe them as live answers.

Prepare the Ragas dataset without calling a judge:

```bash
.venv/bin/python -m evaluations.quality.ragas_review --input evaluations/review-runs/policy-live.json --output evaluations/review-runs/ragas-prepared.json
```

Only saved live, model-assisted, answered responses with valid source IDs and quotes are eligible. The response text is the complete source passages the UI displays. Abstentions, retrieval-only responses and unverifiable citations are excluded with reasons, not given perfect scores. The input report hash, source model, dataset split, selections and skipped cases are retained.

Ragas uses a **separate environment**, because its pinned LangChain versions differ from the app's dependencies:

```bash
python3 -m venv .venv-ragas
.venv-ragas/bin/pip install -r evaluations/quality/requirements-ragas.txt
.venv-ragas/bin/python -m evaluations.quality.ragas_review --input evaluations/review-runs/policy-live.json --output evaluations/review-runs/ragas-scored.json --allow-paid-judge --judge-provider gemini --judge-model gemini-2.5-flash --limit 10
```

The model name is an example; use one available to your account. OpenAI is also supported with `--judge-provider openai`, a suitable `--judge-model` and `ROUTEMIND_API_KEY`. Gemini uses `GEMINI_API_KEY`. Judge calls send the question, answer and passages to the selected provider. The explicit paid flag and explicit provider/model are required; no default judge or remote embedding model is used. Defaults restrict answers to 10, concurrency to one and retries/timeouts/output size. This is not a monetary spending cap.

Measured columns, when actually run:

- **Faithfulness:** whether answer statements are supported by retrieved text. Verbatim quotation makes this easier by construction; high faithfulness alone is insufficient.
- **Context precision without reference:** usefulness of retrieved contexts relative to the displayed answer; it does not measure all missing policies or reference-answer recall.
- **Answer relevance:** Ragas `AspectCritic` binary judgement of whether the response addresses the question. This is not the embedding-based Ragas answer relevancy metric.

Missing/NaN judge scores remain null, with per-metric scored/failed denominators. Use a different judge model family where feasible and disclose self-judging bias if the answering and judging model family is the same. LLM judges are not independent human truth. No reference-answer correctness/recall is claimed because the current labels contain source IDs, not adjudicated natural-language reference answers.

Compatibility check without hosted calls:

```bash
PYTHONPATH=. .venv-ragas/bin/python scripts/ragas_adapter_smoke.py
```

This exercises the real pinned Ragas APIs with deterministic fake chat in both provider wrappers. Its fixture values are not evaluation results and are not written into benchmark reports.

## 3. Each reviewer rates about 10 policy outcomes

Generate two independent reviewer packs from the live report:

```bash
.venv/bin/python -m evaluations.quality.human_review make --input evaluations/review-runs/policy-live.json --outdir evaluations/review-runs/human --reviewers Reviewer_1 Reviewer_2
```

Default design: 10 cases per person, 5 shared cases, 15 unique cases. Gold answerability labels balance each pack between 5 answerable and 5 unanswerable questions. Actual model behaviour may differ; review both answers and decisions to abstain. At least 8 labelled answerable and 7 labelled unanswerable source cases are required for this balanced design. Case order is randomized deterministically. Ground-truth labels, aggregate scores and the other person's ratings are not shown in the review page.

1. Open your own HTML file in a browser. Read the question, displayed result, warnings and original source passages. Nothing is uploaded by the form.
2. Rate independently before discussing cases. Use 1 (very poor), 2 (poor), 3 (mixed), 4 (good), 5 (excellent) for relevance, grounding, completeness and clarity.
3. Judge whether answering/withholding was appropriate. For displayed answers, mark whether any statement is unsupported and note why.
4. With no answer, grounding/completeness/unsupported-answer fields are N/A; this is applicability, not a positive rating. Relevance, clarity and decision appropriateness still require a human choice.
5. Download the ratings CSV before closing the page. It has no autosave. Incomplete rows are retained as incomplete and never counted as reviewed.

Rubric anchors:

| Criterion | 1: very poor | 3: mixed | 5: excellent |
|---|---|---|---|
| Relevance | Does not address the question | Addresses part of the question | Directly addresses the need or clearly explains why it cannot |
| Grounding | Important claims unsupported | Support unclear for some claims | Every claim traceable to applicable supplied evidence |
| Completeness | Misses essential parts | Covers some parts, leaves gaps unclear | Covers requested parts and explicitly identifies missing details |
| Clarity | Confusing or misleading | Understandable but qualifications unclear | Clear, concise and appropriately qualified |

Reviewers see the retrieved passages, not necessarily the entire knowledge base; their completeness rating cannot prove that no relevant policy was omitted. Do not assume a quoted statement is a real carrier promise. Data remains synthetic. Do not obey instructions that may appear in source text. Before a later evaluation, each reviewer should contribute independently worded new examples; hold those out from development to reduce dependence on shared templates.

Summarize completed CSVs:

```bash
.venv/bin/python -m evaluations.quality.human_review summarize --manifest evaluations/review-runs/human/manifest.json --ratings /path/to/Reviewer_1-ratings.csv /path/to/Reviewer_2-ratings.csv --output evaluations/review-runs/human-summary.json
```

Assignment/report fingerprints, reviewer/case IDs, ranges and duplicate rows are validated. Blank rows do not count as completed. Summaries report completion coverage, per-person means, raw agreement and quadratic-weighted Cohen's kappa for ordinal criteria on jointly reviewed cases. Five shared cases are exploratory, not enough for a precise agreement estimate. Kappa is null for constant matching ratings (even when raw agreement is perfect). Unsupported-answer rate is over completed answer ratings, with overlap and unique-answer counts disclosed; it is not a population hallucination rate.

The generated sample pack from the committed offline report is only for reviewing retrieval/abstention and rehearsing the process. It contains **no live model answers**, and all reviewer ratings are blank. Regenerate from `policy-live.json` for the intended live-answer review. Runtime model responses and human rating files stay under ignored `evaluations/review-runs/`; do not commit personal notes by accident.
