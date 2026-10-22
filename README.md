# RouteMind AI

RouteMind AI helps a shipment planner answer: **“What is the best way to move this shipment within my requirements?”** Describe a ground freight shipment in everyday language, compare available routes, and explore how a change in budget, delivery timing or shipment size affects the recommendation.

This is a working demonstration using **synthetic carriers, prices, schedules, capacities and documents**. It supports planning decisions; it does not provide live freight quotes, book shipments or reserve capacity.

## The use case

A planner needs to move fragile electronics from Fremont to Austin. The cheapest option may involve a transfer, while a direct service may arrive sooner at a higher price. The planner must weigh these trade-offs while checking shipment size, handling requirements, budget and delivery timing.

RouteMind brings those choices into one conversation. It asks for missing information, presents feasible options with a cost breakdown, and lets the planner revise the request without starting again.

## Who it is for

- **Shipment planners and logistics coordinators** exploring route, cost and delivery trade-offs.
- **Operations stakeholders** reviewing why a route was recommended and which requirements it meets.
- **Project reviewers** evaluating a practical AI-assisted planning workflow using a repeatable demo scenario.

## What you can do

| Planning need | RouteMind experience |
|---|---|
| Describe a shipment | Enter origin, destination, quantity and requirements in everyday language. |
| Fill in missing details | Answer a clarification before the planner proceeds. |
| Compare choices | Review ranked routes, total costs, arrival times and supporting carrier evidence. |
| Adjust the plan | Ask for faster delivery or a different quantity and compare the revised result with the earlier plan. |
| Understand an infeasible request | Review available, verified changes to budget, deadline or stops when a single change can make the request feasible. |
| Inspect the demo data | Use the read-only Data explorer to browse the records and evidence behind the experience. |

## A five-minute walkthrough

1. Open **Shipment planner** and enter: **“Ship 15 pallets of fragile electronics from Fremont to Austin under $4,000. Find the cheapest route.”**
2. Review the recommendation, cost breakdown, arrival time and supporting evidence. In the seeded scenario, the cheapest recommendation goes through Phoenix for **$2,100**.
3. Ask: **“Make it faster, but keep the budget.”** Compare the revised recommendation with the earlier result. The direct service costs **$3,400** in this scenario.
4. Start a new request with the original shipment and a **$500** budget to see how an infeasible request is handled. Any suggested change is yours to review and apply.
5. Open **Data explorer** to inspect the synthetic schedules, carrier records and supporting documents.

A successful demonstration shows a clear recommendation that meets the stated requirements, an understandable comparison when those requirements change, and an honest response when no feasible route exists. The planner remains responsible for deciding what to do next.

## Project scope and status

The current release is a local demonstration for one ground freight shipment at a time, with routes of up to three scheduled legs. It includes conversational planning, clarification, route comparisons, cited evidence, verified what-if options and a read-only data explorer. The demo uses a fixed November 1–7, 2026 scenario; it does not reflect current operating conditions.

Live traffic, weather, carrier tracking, freight rates and capacity integrations are **not included**. Real-time data integration is deferred. This project demonstrates the planning workflow and does not claim measured operational savings or production readiness.

**Read next:** [Use case and user guide](docs/use-case.md) · [Run locally](#run) · [Architecture diagram and component guide](docs/architecture.md).

The sections below retain the setup instructions and technical reference.

## Run

Python 3.12 is the tested runtime. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open the application on port **8000** in your local browser. `/docs` provides interactive API documentation. `/health` reports database, parser and embedding readiness. No API key is required for the demo. Docker downloads checksum-verified MiniLM weights once during the build and includes them in the image. Native startup downloads them on first use unless cached; set `EMBEDDING_BACKEND=hash` for a fully offline baseline.

Try: **Ship 15 pallets of fragile electronics from Fremont to Austin under $4,000. Find the cheapest route.**

Expected recommendation: Fremont → Phoenix → Austin, **$2,100** ($2,000 transport + $100 transfer). Fastest selects the $3,400 direct service. A $500 ceiling returns `no_route`. Omitting pallets asks a clarification; accepted fields survive the answer and server restart.

The fixed scenario runs **November 1–7, 2026**. Without an explicit ready time the demo starts November 1 at 06:00 UTC, regardless of today's date. Vague dates or reliability requirements trigger clarification. Use structured controls for exact constraints. Times are stored in UTC and displayed in each hub's timezone, including daylight-saving changes.

## Conversational NLP

Try **a dozen pallets of delicate electronics from the Bay Area to Austin under four grand**. The planner shows what it understood: 12 pallets, Fremont → Austin, fragile handling and a $4,000 ceiling. The demo normalizes quantities, currency expressions, aliases and cargo terms. Broader language interpretation is available through the typed LLM parser below.

After receiving a plan, use **Ask a follow-up**:

- “Make it faster, but keep the budget.” Changes the objective while retaining other constraints.
- “What if we ship only eight pallets?” Changes quantity without dropping cargo requirements.
- “Can we arrive earlier without spending more than $500 extra?” Uses the last verified recommendation's price/arrival as reference. Extra spending never silently raises the current hard budget ceiling.
- “Prefer direct, but one transfer is okay if it saves at least $500.” Keeps direct as a preference, not a hard eligibility rule.

Each revision creates a child request with its own ID; previous plans remain unchanged. The UI shows changed fields, price/arrival comparisons, assumptions and request history. An unrecognized revision asks what to change instead of pretending to have understood it. Explicitly named cargo requirements accumulate until explicitly removed or overridden through structured fields.

For an infeasible request, **Verified what-if options** can offer a higher budget, later deadline or more stops. Each option changes one constraint and includes a plan independently checked under that exact change. Click **Try this change** to apply it. Capacity, carrier capabilities and reliability are never silently relaxed; some requests have no safe single-change suggestion.

For pharmaceutical or temperature-sensitive requests, retrieval provides context and clarification asks whether the demo's supported cargo screening is sufficient. It does not certify pharmaceutical suitability or numeric temperature ranges. Only explicit SQL capability flags determine eligibility.

## PostgreSQL / Docker

```bash
docker compose up --build -d
docker compose logs -f api
docker compose down
```

Compose runs PostgreSQL 17 and a non-root API with persistent SQL, evidence and checkpoint volumes. Only the API port is published, bound to the loopback interface. The included database password is a local demo value. Use one API worker. Stopping Compose retains volumes.

For native PostgreSQL, export `DATABASE_URL=postgresql+psycopg://...` before starting. Otherwise SQLite is used under `.data/`. `DATA_DIR` controls generated local state. The generator uses a fixed seed, creates 18 hubs, 10 carriers, 180 services and 58 documents, and never overwrites a populated database.

See [deployment notes](docs/deployment.md) for restricted Docker builders and operational boundaries.

## Language and retrieval modes

| Component | Default: no credentials | Optional model-backed mode |
|---|---|---|
| Parsing | Quantity/currency normalization + conservative rules, `demo-rules-v1` | Context-aware PydanticAI typed extraction with Gemini or OpenAI |
| Chroma embeddings | Learned all-MiniLM-L6-v2 ONNX embeddings; explicit hash fallback if unavailable | Strict MiniLM or a revision-pinned SentenceTransformer |
| Retrieval | Learned semantic similarity + BM25 reciprocal-rank fusion | Dense, BM25 and reranked modes available for evaluation |
| Explanation | Deterministic text from verified plans and actual citation IDs | Kept deterministic to prevent invented numerical claims |

The default language parser is a limited demo, not unrestricted language understanding. It now supports spelled quantities, dozens, currency shorthand, comparative revisions and explicit constraint removal in addition to hub aliases, objectives, stops, reliability and timezone-aware ISO timestamps. Cargo mappings cover fragile/delicate/electronics, secure/high-value, refrigerated/cold-chain/chilled, and hazmat/hazardous materials. Use structured fields for unsupported phrasings. SQL eligibility remains authoritative.

For broader language understanding, choose Gemini or OpenAI. Both use the same typed extraction contract, previous-plan context, validation and deterministic optimizer. Never commit credentials. Native startup does not read `.env` automatically: export variables or use Uvicorn's `--env-file .env`. Compose reads `.env` for its declared settings. Model failures produce a visible warning and fall back to the limited parser. The UI identifies the parser used; `/health` reports provider and whether its key is configured, never its value. Calls have bounded retries and timeouts.

### Enable Gemini on your Mac

Copy `.env.example` to `.env` (or edit your existing `.env`) and set:

```dotenv
ROUTEMIND_PROVIDER=gemini
ROUTEMIND_MODEL=gemini-2.5-flash
GEMINI_API_KEY=your-key-here
```

Obtain your key from [Google AI Studio](https://aistudio.google.com/apikey). Keep it locally; do not paste it into chat. The model name is an example: select a currently available Gemini model supporting function calling in your account. Quotas and pricing depend on your Google account and model. `google` is accepted as a provider alias; a plain `gemini-...` model name also infers the Gemini provider when no provider is set.

After downloading the updated code, run `docker compose up --build -d`. Later key/model changes need only `docker compose up -d --force-recreate api`. Successful requests display `pydantic-ai:gemini:<model-name>`; a warning and demo parser label mean extraction fell back.

For OpenAI instead, set `ROUTEMIND_PROVIDER=openai`, `ROUTEMIND_MODEL=gpt-4.1-mini`, and `ROUTEMIND_API_KEY` to your OpenAI key. Keep only the intended provider/model combination active; keys are never shared between providers.

Default `EMBEDDING_BACKEND=auto` prefers the SHA256-verified Chroma MiniLM model. Docker retains it under `/opt/routemind-models`; native startup uses `DATA_DIR/models`, or `MODEL_CACHE_DIR` if set. If loading fails, auto mode explicitly reports hash-vector fallback in `/health` and the UI. Set `EMBEDDING_BACKEND=minilm` for strict semantic mode (startup fails if unavailable), or `hash` for the offline baseline. Real MiniLM retrieval has been validated. Alternatively install `.[semantic]` and configure `sentence-transformers`, `EMBEDDING_MODEL` and an exact reviewed `EMBEDDING_REVISION`. Collections are separated by embedding version, so upgrading preserves old stored data while building a compatible index.

No live LLM calls were tested because no credentials are configured. Both provider-selection paths, typed outputs and conversation context are tested using PydanticAI test models. No live-model quality or token-cost claim is made. The demo and local semantic embeddings need no paid LLM key.

## Architecture and correctness

![RouteMind architecture: request parsing, clarification, retrieval, deterministic optimization and verification](docs/architecture.png)

[Full-size diagram](docs/architecture.png) · [Component guide](docs/architecture.md) · [Editable diagram source](docs/architecture.dot).

LangGraph owns orchestration. Its persistent SQLite checkpointer saves node states using the unique request ID as `thread_id`; SQL stores externally visible results. Clarification re-enters the same thread; revisions start a new thread linked by `parent_request_id`, with the latest constraints and last verified recommendation as context. `conversation_id` is caller metadata, not an authorization key. Mid-request crashes are not automatically replayed through HTTP; completed and clarification states are restored.

The optimizer enumerates **all acyclic scheduled paths up to three legs**, avoiding unsafe dominance pruning that could discard requested alternatives. It enforces capacity, minimum per-carrier reliability, capabilities, ready time, transfer buffers/fees, budget, deadline and stops. Cost is integer USD cents. Cheapest sorts by cost then arrival; fastest by arrival then cost. Minimal handling breaks ties after the primary objective. With `prefer_direct=true` under cheapest, a feasible direct route is preferred unless a transfer saves at least `transfer_savings_threshold_cents`; without a threshold it only breaks equal-cost ties. Under fastest it only breaks equal-arrival ties. Exact ties use schedule IDs. Carrier rates are never multiplied into a made-up route reliability.

Every returned plan is independently recomputed from authoritative SQL rows before explanation. Chroma never prunes feasible routes or authorizes eligibility. Retrieved text is untrusted evidence, never workflow instructions. Citations include stable IDs, version and synthetic provenance. Trace records identify selected schedules, parser mode and workflow nodes. Rejection counts describe **search transitions**, not independent routes or a minimal infeasibility proof.

For simplicity, a scheduled service contains its route and price rather than separate leg/rate entities. PostgreSQL uses timezone-aware timestamps, foreign keys and check constraints. Request results are JSON text. Capabilities remain explicit SQL records. The 58 documents comprise 50 carrier passages, four authored handling notes and four planning cases.

## API

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/plans \
  -H 'Content-Type: application/json' \
  -d '{"message":"15 pallets of fragile electronics from Fremont to Austin under $4,000; cheapest"}'
```

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/plans` | `message`, optional `conversation_id` and structured `constraints` |
| POST | `/api/v1/plans/{id}/clarify` | Answer with `message` and/or partial `constraints` |
| POST | `/api/v1/plans/{id}/revise` | Follow-up to completed/no-route request; creates an immutable child |
| GET | `/api/v1/plans/{id}` | Persisted state |
| GET | `/api/v1/plans/{id}/alternatives` | Up to three ranked plans |
| GET | `/api/v1/hubs` | Names, aliases, timezones and transfer rules |
| GET | `/health` | Database and evidence readiness |

Statuses are `completed`, `needs_clarification`, `no_route`, `error`. Budgets use `max_budget_cents`; dates require timezone offsets; reliability is 0–1; `max_stops` is 0–2. Structured fields override extraction. Explicit null clears an optional constraint. Clarification retains prior fields and unresolved questions; use `/revise` to change a completed request. Relative budget/arrival operations are resolved deterministically from saved context; the LLM never invents reference prices or timestamps.

## Validation

```bash
.venv/bin/pytest -q
.venv/bin/python -m evaluations.run
# Compare embedding backends on the same labeled corpus:
EMBEDDING_BACKEND=hash .venv/bin/python -m evaluations.run
EMBEDDING_BACKEND=minilm .venv/bin/python -m evaluations.run
# Opt-in integration test with actual learned model weights:
RUN_SEMANTIC_TESTS=1 .venv/bin/pytest tests/test_semantic.py -q
# Dedicated PostgreSQL test database:
TEST_DATABASE_URL='postgresql+psycopg://user:password@host/testdb' .venv/bin/pytest -q
# Optional real browser smoke test, with the API already running:
.venv/bin/pip install '.[ui-test]'
.venv/bin/playwright install chromium
.venv/bin/python scripts/ui_smoke.py
```

The browser script discovers installed Chromium or uses Playwright's browser; `BROWSER_BIN` overrides it. It checks routing, clarification, conversational revisions, price/arrival comparison, applying verified suggestions, reload persistence, mobile layout and JavaScript errors. Screenshots go to `/tmp/routemind-ui`. Tests force offline parsing and hash embeddings; learned-model integration is opt-in. Use a dedicated test database: tests seed an empty database and do not drop tables.

The suite includes 20 random tiny networks checked against an independent exhaustive oracle, known optimal fixtures, constraint failures, timezone equivalence, tamper detection, retrieval/model failures and restart recovery. CI runs SQLite and PostgreSQL tests. See [benchmark report](evaluations/REPORT.md) and [actual results](evaluations/results.json); synthetic regression scores are not production accuracy claims.

## Scope

This is a local, single-worker MVP with a 16 KiB POST limit, typed validation, in-process per-IP write limits, CORS allowlists, parameterized SQL and redacted HTTP errors. It has no accounts, tenant isolation, production migrations, distributed limiting or real carrier integrations. Keep real shipment data out of the shared demo. SQL retains messages/results; browser storage keeps only the last request ID. Retention management is a deployment concern.

Advanced cross-encoder/Ragas experiments, real-world labeled data, live LLM quality evaluation and public deployment are deferred. The delivered scope prioritizes a working, testable planner without paid model access.

### Read-only data explorer

Open **Data explorer** in the web UI sidebar (or visit `/explorer`). Browse hubs, carriers, capabilities, schedules, SQL evidence documents and the active ChromaDB collection. Search all fields, page through records and open **View** for complete document text or stored vector dimensions, norm and embedding values. Prices use US cents and timestamps use UTC. All reference data is synthetic; shipment conversations are excluded.

Explorer APIs accept GET only: `/api/v1/explorer` (counts and active model), `/api/v1/explorer/tables/{name}`, `/api/v1/explorer/vectors`, and `/api/v1/explorer/vectors/{source_id}`. Listings support literal `q`, `limit` (1–100), and `offset` parameters. The vector browser reads the active persisted Chroma index; it does not perform semantic retrieval or require a separate Chroma installation.
