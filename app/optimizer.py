"""Exact bounded schedule enumeration, deliberately avoiding unsafe label pruning.

For this 180-service MVP, all acyclic paths up to three legs are inexpensive to
enumerate. Keeping dominated paths preserves the requested top-three alternatives.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from app.schemas import Constraints


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def search(network, c: Constraints):
    hubs, carriers, schedules = network
    outgoing = defaultdict(list)
    for s in schedules:
        outgoing[s["origin"]].append(s)
    rejected = Counter()
    solutions = []

    def visit(hub, arrival, cost, path, seen):
        if hub == c.destination and path:
            solutions.append(make_plan(path, hubs, carriers, c.pallets))
            return
        if len(path) >= c.max_stops + 1:
            rejected["max_stops"] += 1
            return
        for s in outgoing[hub]:
            carrier = carriers[s["carrier_id"]]
            departure, end = dt(s["departure_at"]), dt(s["arrival_at"])
            new_cost = cost + s["base_cost_cents"] + s["per_pallet_cents"] * c.pallets + (hubs[hub]["transfer_cents"] if path else 0)
            reason = None
            if s["destination"] in seen:
                reason = "cycle"
            elif s["capacity_pallets"] < c.pallets:
                reason = "capacity"
            elif not set(c.required_capabilities).issubset(carrier["capabilities"]):
                reason = "capability_unverified"
            elif c.min_on_time_rate is not None and carrier["on_time_rate"] < c.min_on_time_rate:
                reason = "reliability"
            elif departure < arrival + (timedelta(minutes=hubs[hub]["connection_minutes"]) if path else timedelta()):
                reason = "connection_or_ready_time"
            elif c.delivery_deadline is not None and end > c.delivery_deadline:
                reason = "deadline"
            elif c.max_budget_cents is not None and new_cost > c.max_budget_cents:
                reason = "budget"
            if reason:
                rejected[reason] += 1
                continue
            visit(s["destination"], end, new_cost, path + [s], seen | {s["destination"]})

    visit(c.origin, c.ready_at, 0, [], {c.origin})
    def key(p):
        primary = (p["total_cost_cents"], p["arrival_at"]) if c.optimization_goal == "cheapest" else (p["arrival_at"], p["total_cost_cents"])
        if c.minimal_handling:
            primary = (primary[0], p["leg_count"], primary[1])
        return (*primary, p["plan_id"])
    solutions.sort(key=key)
    if c.prefer_direct and solutions:
        direct = [p for p in solutions if p['leg_count']==1]
        if direct:
            preferred = direct[0]
            if c.optimization_goal == 'cheapest':
                savings = preferred['total_cost_cents']-solutions[0]['total_cost_cents']
                threshold = c.transfer_savings_threshold_cents
                use_direct = savings == 0 or (threshold is not None and savings < threshold)
            else:
                use_direct = preferred['arrival_at']==solutions[0]['arrival_at']
            if use_direct:
                solutions.remove(preferred)
                solutions.insert(0,preferred)
    return solutions[:3], dict(rejected), len(solutions)


def make_plan(path, hubs, carriers, pallets):
    legs = []
    for index, s in enumerate(path):
        carrier = carriers[s["carrier_id"]]
        legs.append({**s, "carrier_name": carrier["name"], "on_time_rate": carrier["on_time_rate"],
            "verified_capabilities": carrier["capabilities"],
            "transport_cost_cents": s["base_cost_cents"] + s["per_pallet_cents"] * pallets,
            "transfer_cost_cents": hubs[s["origin"]]["transfer_cents"] if index else 0})
    transport = sum(s["transport_cost_cents"] for s in legs)
    transfers = sum(s["transfer_cost_cents"] for s in legs)
    ids = [path[0]["origin"]] + [s["destination"] for s in path]
    return dict(plan_id="plan-" + "-".join(s["id"] for s in path), route=[hubs[i]["name"] for i in ids], hub_ids=ids,
        total_cost_cents=transport+transfers, transport_cost_cents=transport, transfer_cost_cents=transfers,
        departure_at=path[0]["departure_at"], arrival_at=path[-1]["arrival_at"], leg_count=len(path),
        transit_hours=round((dt(path[-1]["arrival_at"]) - dt(path[0]["departure_at"])).total_seconds()/3600, 2), legs=legs)


def verify_plan(plan, network, c):
    """Independently recompute constraints from authoritative schedules, not output legs."""
    hubs, carriers, rows = network
    schedules = {s["id"]: s for s in rows}
    path = [schedules[leg["id"]] for leg in plan["legs"]]
    if not 1 <= len(path) <= c.max_stops + 1:
        raise ValueError("Invalid leg count")
    hub, arrival, cost, seen = c.origin, c.ready_at, 0, {c.origin}
    for index, s in enumerate(path):
        carrier = carriers[s["carrier_id"]]
        if s["origin"] != hub or s["destination"] in seen:
            raise ValueError("Discontinuous or cyclic route")
        if s["capacity_pallets"] < c.pallets or not set(c.required_capabilities) <= set(carrier["capabilities"]):
            raise ValueError("Capacity or capability failure")
        if c.min_on_time_rate is not None and carrier["on_time_rate"] < c.min_on_time_rate:
            raise ValueError("Reliability failure")
        buffer = timedelta(minutes=hubs[hub]["connection_minutes"]) if index else timedelta()
        if dt(s["departure_at"]) < arrival + buffer or dt(s["arrival_at"]) <= dt(s["departure_at"]):
            raise ValueError("Schedule failure")
        cost += s["base_cost_cents"] + s["per_pallet_cents"] * c.pallets
        if index:
            cost += hubs[hub]["transfer_cents"]
        hub, arrival = s["destination"], dt(s["arrival_at"])
        seen.add(hub)
    if hub != c.destination or (c.delivery_deadline and arrival > c.delivery_deadline) or (c.max_budget_cents is not None and cost > c.max_budget_cents):
        raise ValueError("Destination, deadline or budget failure")
    recomputed = make_plan(path, hubs, carriers, c.pallets)
    if plan != recomputed or cost != plan["total_cost_cents"]:
        raise ValueError("Plan differs from authoritative recomputation")
    return True
