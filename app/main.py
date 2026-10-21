import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from langgraph.checkpoint.sqlite import SqliteSaver
from app.database import Database
from app.rag import Retriever
from app.schemas import PlanInput, Clarification
from app.seed import seed, SCENARIO_START
from app.workflow import build_workflow

log = logging.getLogger("routemind")
STATIC = Path(__file__).parent / "static"


def create_app(database_url=None):
    # A single worker owns workflow updates; persistent SQL state survives restarts.
    mutation_lock = threading.Lock()
    rate_lock = threading.Lock()
    calls = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app):
        db = Database(database_url)
        seed(db)
        app.state.db = db
        app.state.retriever = Retriever(db)
        checkpoint_conn = sqlite3.connect(Path(os.getenv("DATA_DIR", ".data")) / "checkpoints.db", check_same_thread=False)
        app.state.checkpointer = SqliteSaver(checkpoint_conn)
        app.state.workflow = build_workflow(db, app.state.retriever, app.state.checkpointer)
        try:
            yield
        finally:
            checkpoint_conn.close()
            db.engine.dispose()

    app = FastAPI(title="RouteMind AI", version="0.1.0", lifespan=lifespan,
                  description="Synthetic scheduled ground freight planning. No booking, live quotes or capacity reservations.")
    origins = [s.strip() for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def limits(request: Request, call_next):
        # Enforce an actual streamed body limit, even when Content-Length is absent.
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"detail": "Request body exceeds 16 KiB"}, status_code=413)
            request._body = bytes(body)
            ident = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with rate_lock:
                # Prune idle client records so the limiter remains bounded.
                for old in list(calls):
                    if not calls[old] or calls[old][-1] < now-60:
                        del calls[old]
                queue = calls[ident]
                while queue and queue[0] < now-60:
                    queue.popleft()
                if len(queue) >= 30:
                    return JSONResponse({"detail": "Rate limit: 30 planning writes per minute"}, status_code=429)
                queue.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def execute(state):
        start = time.perf_counter()
        try:
            result = dict(app.state.workflow.invoke(state, config={"recursion_limit": 12, "configurable": {"thread_id": state["request_id"]}}))
        except Exception as exc:
            log.exception("planning_failed request_id=%s", state["request_id"])
            result = {**state, "status": "error", "error": "Planning failed. Check server logs using the request ID.", "plans": [], "recommended_plan": None}
        result["latency_ms"] = round((time.perf_counter()-start)*1000, 2)
        result.pop("overrides", None)
        app.state.db.save(result)
        log.info(json.dumps({"request_id": result["request_id"], "status": result["status"], "latency_ms": result["latency_ms"],
            "parser_mode": result.get("parser_mode"), "schedule_ids": [l["id"] for l in (result.get("recommended_plan") or {}).get("legs", [])],
            "evidence_ids": [e["source_id"] for e in result.get("evidence", [])], "prompt_version": "extract-v1"}))
        return result

    def load(request_id):
        state = app.state.db.load(request_id)
        if not state:
            raise HTTPException(404, "Plan request not found")
        return state

    @app.get("/health")
    def health():
        with app.state.db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        count = app.state.retriever.collection.count()
        return {"status": "ok", "database": app.state.db.engine.dialect.name, "evidence_documents": count,
            "embedding_model": app.state.retriever.model_version, "parser": "pydantic-ai" if os.getenv("ROUTEMIND_MODEL") else "demo-rules-v1",
            "data_type": "synthetic", "scenario_start": SCENARIO_START,
            'embedding_backend':app.state.retriever.backend,'retrieval_warning':app.state.retriever.warning,
            'llm_configured':bool(os.getenv('ROUTEMIND_MODEL') and os.getenv('ROUTEMIND_API_KEY'))}

    @app.get("/api/v1/hubs")
    def get_hubs():
        hs, _, _ = app.state.db.network()
        return [{**h, "aliases": json.loads(h["aliases"])} for h in hs.values()]

    @app.post("/api/v1/plans")
    def plan(body: PlanInput):
        state = {"request_id": str(uuid.uuid4()), "conversation_id": body.conversation_id,
            "message": body.message, "messages": [body.message], "constraints": {},
            "overrides": body.constraints.model_dump(mode="json", exclude_unset=True) if body.constraints else {},
            "plans": [], "recommended_plan": None, "evidence": [], "warnings": [], "trace": [],
            "data_type": "synthetic", "status": "planning"}
        with mutation_lock:
            return execute(state)

    @app.post("/api/v1/plans/{request_id}/clarify")
    def clarify(request_id: str, body: Clarification):
        with mutation_lock:
            state = load(request_id)
            if state["status"] != "needs_clarification":
                raise HTTPException(409, "Only requests awaiting clarification can be resumed; submit a new plan to change a completed request")
            if state.get('clarification_count',0) >= 10 or len(state['messages']) >= 30:
                raise HTTPException(409, "Clarification limit reached. Start a new request with structured constraints.")
            state.update(message=body.message, messages=state["messages"] + [body.message],
                clarification_count=state.get('clarification_count',0)+1,
                overrides=body.constraints.model_dump(mode="json", exclude_unset=True) if body.constraints else {}, plans=[], evidence=[], recommended_plan=None)
            return execute(state)

    @app.post('/api/v1/plans/{request_id}/revise')
    def revise(request_id: str, body: Clarification):
        """Create an immutable child plan; the previous recommendation is its reference."""
        with mutation_lock:
            parent=load(request_id)
            if parent['status'] not in {'completed','no_route'}:
                raise HTTPException(409,'Answer pending clarifications before revising this request')
            if len(parent['messages']) >= 30:
                raise HTTPException(409,'Conversation limit reached. Start a new request.')
            state={'request_id':str(uuid.uuid4()),'parent_request_id':request_id,
                'conversation_id':parent.get('conversation_id') or parent['request_id'],
                'message':body.message,'messages':parent['messages']+[body.message],
                'constraints':parent['constraints'], 'baseline_plan':parent.get('recommended_plan') or parent.get('baseline_plan'),
                'overrides':body.constraints.model_dump(mode='json',exclude_unset=True) if body.constraints else {},
                'plans':[],'recommended_plan':None,'comparison':None,'suggestions':[],
                'evidence':[],'warnings':[],'trace':[],'data_type':'synthetic','status':'planning'}
            return execute(state)

    @app.get("/api/v1/plans/{request_id}")
    def get_plan(request_id: str):
        return load(request_id)

    @app.get("/api/v1/plans/{request_id}/alternatives")
    def alternatives(request_id: str):
        state = load(request_id)
        return {"request_id": request_id, "status": state["status"], "plans": state["plans"], "data_type": "synthetic"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
