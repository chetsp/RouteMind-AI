from copy import deepcopy
from datetime import timedelta
from itertools import product
import random
import pytest
from app.optimizer import search, verify_plan, dt
from app.schemas import Constraints
from app.seed import SCENARIO_START


def constraint(**kwargs):
    return Constraints(origin="FRE", destination="AUS", pallets=15, ready_at=SCENARIO_START, **kwargs)


def test_known_optima_and_costs(network):
    plans, reasons, _ = search(network, constraint(required_capabilities=["fragile"]))
    assert [p["total_cost_cents"] for p in plans] == [210000, 275000, 340000]
    assert plans[0]["transfer_cost_cents"] == 10000
    assert plans[0]["hub_ids"] == ["FRE", "PHX", "AUS"]
    assert reasons["capability_unverified"] > 0
    for p in plans:
        assert verify_plan(p, network, constraint(required_capabilities=["fragile"]))
    fastest, _, _ = search(network, constraint(optimization_goal="fastest"))
    assert fastest[0]["legs"][0]["id"] == "S003"


@pytest.mark.parametrize("fields,reason", [
    ({"max_budget_cents":50000},"budget"),
    ({"delivery_deadline":"2026-11-01T20:00:00Z"},"deadline"),
    ({"required_capabilities":["hazmat"]},"capability_unverified"),
    ({"min_on_time_rate":1},"reliability"),
])
def test_infeasible(network, fields, reason):
    plans, reasons, _ = search(network, constraint(**fields))
    assert plans == [] and reasons[reason] > 0


def test_capacity_connections_direct_and_cold_chain(network):
    normal, reasons, _ = search(network, constraint())
    assert reasons["capacity"] and reasons["connection_or_ready_time"]
    assert all("S006" not in p["plan_id"] and "S007" not in p["plan_id"] for p in normal)
    direct, _, _ = search(network, constraint(max_stops=0))
    assert all(p["leg_count"] == 1 for p in direct)
    cold, _, _ = search(network, constraint(required_capabilities=["refrigerated"]))
    assert cold[0]["plan_id"] == "plan-S008-S009"


def test_independent_verifier_detects_tampering(network):
    plans, _, _ = search(network, constraint())
    bad = deepcopy(plans[0]); bad["total_cost_cents"] -= 1
    with pytest.raises(ValueError): verify_plan(bad, network, constraint())
    bad = deepcopy(plans[0]); bad["legs"][0]["capacity_pallets"] = 999
    with pytest.raises(ValueError): verify_plan(bad, network, constraint())


def oracle(network, c):
    """Independent cartesian enumeration for tiny fixtures; no search code reused."""
    hs, cs, rows = network
    valid = []
    for count in range(1,c.max_stops+2):
        for chain in product(rows, repeat=count):
            if chain[0]["origin"] != c.origin or chain[-1]["destination"] != c.destination:
                continue
            ids = [chain[0]["origin"]]+[s["destination"] for s in chain]
            if len(set(ids)) != len(ids): continue
            if any(a["destination"] != b["origin"] for a,b in zip(chain,chain[1:])): continue
            if dt(chain[0]["departure_at"]) < c.ready_at: continue
            if any(dt(b["departure_at"]) < dt(a["arrival_at"])+timedelta(minutes=hs[a["destination"]]["connection_minutes"]) for a,b in zip(chain,chain[1:])): continue
            if any(s["capacity_pallets"] < c.pallets for s in chain): continue
            if any(not set(c.required_capabilities) <= set(cs[s["carrier_id"]]["capabilities"]) for s in chain): continue
            if c.min_on_time_rate is not None and any(cs[s["carrier_id"]]["on_time_rate"] < c.min_on_time_rate for s in chain): continue
            cost = sum(s["base_cost_cents"]+s["per_pallet_cents"]*c.pallets for s in chain)+sum(hs[s["origin"]]["transfer_cents"] for s in chain[1:])
            if c.max_budget_cents is not None and cost > c.max_budget_cents: continue
            arrival = chain[-1]["arrival_at"]
            if c.delivery_deadline and dt(arrival) > c.delivery_deadline: continue
            ident = "plan-"+"-".join(s["id"] for s in chain)
            key = (cost,arrival,ident) if c.optimization_goal=="cheapest" else (arrival,cost,ident)
            valid.append((key,ident))
    return [ident for _,ident in sorted(valid)[:3]]


@pytest.mark.parametrize("seed", range(20))
def test_top_three_against_exhaustive_oracle(seed):
    rng = random.Random(seed)
    hs = {i:{"name":i,"connection_minutes":30,"transfer_cents":100} for i in "ABCD"}
    cs = {"C":{"name":"C","on_time_rate":.97,"capabilities":["fragile"]}}
    rows=[]
    base=dt(SCENARIO_START)
    for i in range(12):
        o,d = rng.sample(list(hs),2)
        start = rng.randint(0,20)
        rows.append(dict(id=str(i),origin=o,destination=d,carrier_id="C",departure_at=(base+timedelta(hours=start)).isoformat(),arrival_at=(base+timedelta(hours=start+2)).isoformat(),capacity_pallets=rng.randint(1,20),base_cost_cents=rng.randint(10,100)*100,per_pallet_cents=100))
    net=hs,cs,rows
    for goal in ("cheapest","fastest"):
        c=Constraints(origin="A",destination="D",pallets=5,ready_at=SCENARIO_START,optimization_goal=goal,max_budget_cents=20000)
        actual,_,_=search(net,c)
        assert [p["plan_id"] for p in actual] == oracle(net,c)
        for p in actual: assert verify_plan(p,net,c)


def test_timezone_equivalence(network):
    a=constraint(); b=constraint(); b.ready_at=dt("2026-10-31T23:00:00-07:00")
    assert search(network,a)[0] == search(network,b)[0]
