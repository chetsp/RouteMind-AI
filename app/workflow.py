import logging
import json
import time
from typing import TypedDict
from langgraph.graph import StateGraph, END, START
from pydantic import ValidationError
from app.parser import extract, normalize_hub, demo_extract
from app.schemas import Constraints
from app.seed import SCENARIO_START
from app.optimizer import search, verify_plan
from app.language import normalize_language, resolve_operations
from app.suggestions import verified_suggestions

log = logging.getLogger("routemind")


class State(TypedDict, total=False):
    request_id: str
    conversation_id: str | None
    message: str
    messages: list[str]
    overrides: dict
    constraints: dict
    ambiguities: dict
    questions: list[str]
    status: str
    plans: list
    recommended_plan: dict | None
    evidence: list
    warnings: list[str]
    rejection_counts: dict
    feasible_route_count: int
    explanation: str
    trace: list
    parser_mode: str
    data_type: str
    error: str | None
    latency_ms: float
    parent_request_id: str | None
    baseline_plan: dict | None
    interpretation: dict
    comparison: dict | None
    suggestions: list
    cargo_interpretation: list
    clarification_count: int


def ambiguity_key(question):
    q = question.lower()
    if 'which constraint' in q: return 'revision'
    if "pallet" in q: return "pallets"
    if "objective" in q: return "optimization_goal"
    if "budget" in q: return "max_budget_cents"
    if "on-time" in q: return "min_on_time_rate"
    if "timestamp" in q or "date" in q: return "dates"
    if "cargo review" in q: return "required_capabilities"
    if "budget" in q or "extra-cost" in q: return "max_budget_cents"
    if "previous plan" in q or "earlier arrival" in q: return "dates"
    if "change" in q: return "revision"
    return "locations"


def build_workflow(db, retriever, checkpointer=None):
    def trace(state, node):
        return state.get("trace", []) + [{"node": node, "at": time.time()}]

    def parse(state):
        hs, _, _ = db.network()
        warnings = list(state.get("warnings", []))
        previous = state.get("constraints", {})
        try:
            fields, questions, mode = extract(state["message"], hs, previous, state.get('baseline_plan'))
        except Exception as exc:
            log.warning("parser_fallback request_id=%s error_type=%s", state["request_id"], type(exc).__name__)
            fields, questions = demo_extract(state["message"], hs, previous)
            mode = "demo-rules-v1 (LLM unavailable)"
            warnings.append("LLM extraction unavailable; the limited demo parser was used. Review structured constraints.")
        fields, relative_questions, assumptions = resolve_operations(fields, previous, state.get('baseline_plan'))
        if any(any(term in m.lower() for term in ('pharmaceutical','vaccine','temperature-sensitive')) for m in state['messages']):
            assumptions.append('Only the supported cargo capability flags are screened. Pharmaceutical certification and numeric temperature ranges are not modeled.')
        questions += relative_questions
        fields.update(state.get("overrides", {}))
        if state.get('parent_request_id') and not fields and not questions:
            questions.append('Which constraint would you like to change? Try make it faster, eight pallets, or budget $3,000.')
        merged = {**previous, **fields}
        ambiguities = dict(state.get("ambiguities", {}))
        for key in list(ambiguities):
            if key in fields or (key=='revision' and fields) or (key == "dates" and ("ready_at" in fields or "delivery_deadline" in fields)) or (key == "locations" and "origin" in fields and "destination" in fields):
                ambiguities.pop(key)
        for q in questions:
            key = ambiguity_key(q)
            overrides = state.get("overrides", {})
            if key in overrides or (key == "dates" and ("ready_at" in overrides or "delivery_deadline" in overrides)) or (key == "locations" and "origin" in overrides and "destination" in overrides):
                continue
            ambiguities[key] = q
        changes = {k:{'before':previous.get(k),'after':v} for k,v in fields.items() if previous.get(k)!=v}
        changes = json.loads(json.dumps(changes,default=str))
        return {"constraints": merged, "ambiguities": ambiguities, "parser_mode": mode,
                'interpretation':{'normalized_message':normalize_language(state['message']),'changes':changes,'assumptions':assumptions},
                "warnings": list(dict.fromkeys(warnings)), "trace": trace(state, "parse"), "error": None}

    def validate(state):
        raw = json.loads(json.dumps(state["constraints"], default=lambda v: v.isoformat()))
        questions = list(state["ambiguities"].values())
        hs, _, _ = db.network()
        for key in ("origin", "destination"):
            value = normalize_hub(raw.get(key), hs)
            raw[key] = value
            if not value:
                questions.append(f"Choose a supported {key} hub.")
        if not raw.get("pallets"):
            questions.append("How many pallets are being shipped?")
        if not raw.get("ready_at"):
            # The fixed scenario window is an explicit demo setting, not a parsed date.
            raw["ready_at"] = SCENARIO_START
        if raw.get("origin") and raw["origin"] == raw.get("destination"):
            questions.append("Origin and destination must be different hubs.")
        try:
            parsed = Constraints.model_validate(raw).model_dump(mode="json")
        except ValidationError as exc:
            questions.extend(f"{'.'.join(str(x) for x in e['loc']) or 'constraints'}: {e['msg']}" for e in exc.errors(include_input=False))
            parsed = raw
        evidence = state.get('evidence',[])
        if any('Cargo review' in q for q in questions):
            try: evidence = retriever.query(state['message'],k=5,mode='hybrid')
            except Exception: evidence = []
        return {"constraints": parsed, "questions": list(dict.fromkeys(questions)), 'evidence':evidence,
            "status": "needs_clarification" if questions else "planning", "trace": trace(state, "validate")}

    def retrieve(state):
        c = Constraints.model_validate(state["constraints"])
        query = state['message'] + ' ' + ' '.join(c.required_capabilities) + f' {c.origin} {c.destination}'
        try:
            evidence = retriever.query(query, k=8, mode="hybrid")
            warnings = state.get("warnings", []) + ([retriever.warning] if getattr(retriever,'warning',None) else [])
        except Exception as exc:
            log.warning("retrieval_unavailable request_id=%s error_type=%s", state["request_id"], type(exc).__name__)
            evidence = []
            warnings = state.get("warnings", []) + ["Carrier evidence retrieval unavailable. Routes use verified SQL eligibility only; no prose capability claims are made."]
        interpretation = [{'capability':cap,'policy':'SQL carrier flag must be explicitly enabled on every leg.',
            'source_ids':[e['source_id'] for e in evidence if cap in e['text'].lower()],
            'status':'requested; eligibility checked by SQL, not inferred from similarity'} for cap in c.required_capabilities]
        return {"evidence": evidence, "warnings": list(dict.fromkeys(warnings)), 'cargo_interpretation':interpretation, "trace": trace(state, "retrieve")}

    def optimize(state):
        plans, reasons, count = search(db.network(), Constraints.model_validate(state["constraints"]))
        return {"plans": plans, "rejection_counts": reasons, "feasible_route_count": count, "trace": trace(state, "optimize")}

    def verify(state):
        network = db.network()
        for p in state["plans"]:
            verify_plan(p, network, Constraints.model_validate(state["constraints"]))
        return {"trace": trace(state, "verify")}

    def explain(state):
        plans = state["plans"]
        evidence = list(state.get('evidence',[]))
        if plans and evidence:
            selected = {leg['carrier_id']:leg['carrier_name'] for leg in plans[0]['legs']}
            missing = set(selected)-{e.get('carrier_id') for e in evidence}
            if missing:
                try:
                    # Retrieval can now use verified carrier IDs; it still cannot
                    # authorize services or alter the optimizer's chosen route.
                    query = ' '.join(selected[i] for i in sorted(missing))+' '+' '.join(state['constraints']['required_capabilities'])
                    extra = retriever.query(query,k=min(6,2*len(missing)),mode='hybrid',carrier_ids=missing)
                    known = {e['source_id'] for e in evidence}
                    evidence += [e for e in extra if e['source_id'] not in known and e.get('carrier_id') in missing]
                except Exception as exc:
                    log.warning('explanation_evidence_unavailable request_id=%s error_type=%s',state['request_id'],type(exc).__name__)
        c = Constraints.model_validate(state['constraints'])
        suggestions = verified_suggestions(db.network(),c,plans)
        comparison = None
        baseline = state.get('baseline_plan')
        if not plans:
            reasons = ", ".join(f"{k.replace('_', ' ')} ({v} rejected search transitions)" for k,v in sorted(state["rejection_counts"].items())) or "no scheduled outgoing path"
            text = f"No feasible route in the synthetic schedule window. Search diagnostics: {reasons}. Counts describe transitions, not independent alternative routes. Try relaxing a constraint or changing the ready time."
            if suggestions: text += ' Verified possible changes: ' + ' '.join(s['summary'] for s in suggestions)
        else:
            p = plans[0]
            goal = state["constraints"]["optimization_goal"]
            ranking = 'the best-ranked under your explicit direct-route preference' if c.prefer_direct else f'the {goal}'
            text = (f"Recommended {' → '.join(p['route'])}: ${p['total_cost_cents']/100:,.2f} USD "
                f"(${p['transport_cost_cents']/100:,.2f} transport + ${p['transfer_cost_cents']/100:,.2f} transfers), "
                f"arriving {p['arrival_at']}. This is {ranking} feasible route among {state['feasible_route_count']} "
                f"scheduled paths within the specified constraints and three-leg limit. "
                "Capacity, connections, price and eligibility were independently verified against SQL records. "
                "On-time percentages describe each carrier; no combined route reliability is claimed.")
            carriers = {leg["carrier_id"] for leg in p["legs"]}
            citations = [e["source_id"] for e in evidence if e["carrier_id"] in carriers]
            if citations:
                text += " Supporting synthetic carrier descriptions: " + ", ".join(citations) + "."
            else:
                text += " No matching carrier profile was retrieved for the recommendation; capability claims rely on the structured carrier records shown in the legs."
            if baseline:
                from app.optimizer import dt
                comparison={'previous_plan_id':baseline['plan_id'],'previous_total_cost_cents':baseline['total_cost_cents'],
                    'previous_arrival_at':baseline['arrival_at'], 'cost_delta_cents':p['total_cost_cents']-baseline['total_cost_cents'],
                    'arrival_delta_minutes':round((dt(p['arrival_at'])-dt(baseline['arrival_at'])).total_seconds()/60,2)}
        return {"recommended_plan": plans[0] if plans else None, "status": "completed" if plans else "no_route",
                'suggestions':suggestions,'comparison':comparison,
                'evidence':evidence,
                "explanation": text, "trace": trace(state, "explain")}

    graph = StateGraph(State)
    for name, fn in [("parse", parse), ("validate", validate), ("retrieve", retrieve), ("optimize", optimize), ("verify", verify), ("explain", explain)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "validate")
    graph.add_conditional_edges("validate", lambda s: "stop" if s["status"] == "needs_clarification" else "continue", {"stop": END, "continue": "retrieve"})
    graph.add_edge("retrieve", "optimize")
    graph.add_edge("optimize", "verify")
    graph.add_edge("verify", "explain")
    graph.add_edge("explain", END)
    return graph.compile(checkpointer=checkpointer)
