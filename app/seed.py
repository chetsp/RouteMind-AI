"""Deterministic, fictional demonstration network. Never current market data."""
import json
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.database import hubs, carriers, capabilities, schedules, documents

SCENARIO_START = "2026-11-01T06:00:00+00:00"
HUBS = [
    ("FRE", "Fremont", "America/Los_Angeles", ["fremont", "bay area"]),
    ("PHX", "Phoenix", "America/Phoenix", ["phoenix"]),
    ("AUS", "Austin", "America/Chicago", ["austin"]),
    ("LAX", "Los Angeles", "America/Los_Angeles", ["los angeles", "la"]),
    ("DAL", "Dallas", "America/Chicago", ["dallas"]),
    ("DEN", "Denver", "America/Denver", ["denver"]),
    ("SEA", "Seattle", "America/Los_Angeles", ["seattle"]),
    ("PDX", "Portland", "America/Los_Angeles", ["portland"]),
    ("SLC", "Salt Lake City", "America/Denver", ["salt lake city"]),
    ("LAS", "Las Vegas", "America/Los_Angeles", ["las vegas"]),
    ("HOU", "Houston", "America/Chicago", ["houston"]),
    ("SAT", "San Antonio", "America/Chicago", ["san antonio"]),
    ("CHI", "Chicago", "America/Chicago", ["chicago"]),
    ("ATL", "Atlanta", "America/New_York", ["atlanta"]),
    ("NYC", "New York", "America/New_York", ["new york", "nyc"]),
    ("BOS", "Boston", "America/New_York", ["boston"]),
    ("MIA", "Miami", "America/New_York", ["miami"]),
    ("CLT", "Charlotte", "America/New_York", ["charlotte"]),
]
PROFILES = [
    ("C01", "Cobalt Secure Ground", .98, ["fragile", "secure"], "Sealed trailers and controlled handoffs for fragile electronics and high-value freight. Trained teams protect delicate cargo."),
    ("C02", "Mesa Value Freight", .94, [], "Economical general dry freight and standard pallet shipping. Specialized handling is not verified."),
    ("C03", "Glacier Cold Chain", .97, ["refrigerated"], "Temperature-controlled refrigerated trailers for chilled food and cold-chain cargo."),
    ("C04", "Atlas Express", .99, ["fragile", "secure"], "Priority ground service with secure trailers and careful fragile-goods handling."),
    ("C05", "Copper Industrial", .96, ["hazmat"], "Documented hazardous material handling for regulated industrial freight."),
    ("C06", "Prairie Pallet", .92, [], "Standard palletized dry goods service with scheduled regional departures."),
    ("C07", "Summit Protected", .985, ["fragile", "secure", "refrigerated"], "Protected fragile and high-value loads with temperature-controlled equipment."),
    ("C08", "Harbor General", .95, [], "General freight across regional hubs. No specialist equipment is verified."),
    ("C09", "Orion Regulated", .975, ["hazmat", "secure"], "Secure regulated freight with explicit hazardous-material eligibility."),
    ("C10", "Juniper Care", .965, ["fragile"], "Careful loading and padded handling for delicate fragile goods."),
]


def seed(db):
    with db.engine.begin() as conn:
        if conn.execute(select(hubs.c.id).limit(1)).first():
            return  # Never overwrite a populated database.
        conn.execute(hubs.insert(), [dict(id=i, name=n, timezone=t, aliases=json.dumps(a + [i.lower()]), connection_minutes=60, transfer_cents=10000) for i, n, t, a in HUBS])
        conn.execute(carriers.insert(), [dict(id=i, name=n, on_time_rate=r) for i, n, r, _, _ in PROFILES])
        conn.execute(capabilities.insert(), [dict(carrier_id=i, capability=c, enabled=c in caps) for i, _, _, caps, _ in PROFILES for c in ["fragile", "secure", "refrigerated", "hazmat"]])
        start = datetime.fromisoformat(SCENARIO_START)
        rows = []

        def add(i, o, d, c, depart, duration, capacity, base, per):
            rows.append(dict(id=i, origin=o, destination=d, carrier_id=c,
                departure_at=(start + timedelta(hours=depart)).isoformat(),
                arrival_at=(start + timedelta(hours=depart + duration)).isoformat(),
                capacity_pallets=capacity, base_cost_cents=base, per_pallet_cents=per))

        # Known optimum: 15 pallets, cheapest = FRE/PHX/AUS $2,100;
        # fastest = direct Atlas arriving at +32h, $3,400.
        add("S001", "FRE", "PHX", "C01", 2, 14, 24, 40000, 2000)
        add("S002", "PHX", "AUS", "C01", 18, 22, 24, 100000, 2000)
        add("S003", "FRE", "AUS", "C04", 1, 31, 24, 280000, 4000)
        add("S004", "FRE", "LAX", "C10", 3, 8, 20, 35000, 2000)
        add("S005", "LAX", "AUS", "C04", 13, 30, 20, 155000, 3000)
        add("S006", "FRE", "AUS", "C02", 4, 45, 8, 60000, 1000)
        add("S007", "PHX", "AUS", "C02", 16.5, 21, 30, 60000, 1000)  # missed transfer
        add("S008", "FRE", "PHX", "C03", 5, 15, 20, 65000, 3000)
        add("S009", "PHX", "AUS", "C03", 22, 23, 20, 90000, 3000)
        rng = random.Random(42)
        # Remaining network is deliberately separate from handcrafted origin fixtures.
        other = [h[0] for h in HUBS if h[0] not in {"FRE", "PHX", "LAX"}]
        for idx in range(10, 181):
            o, d = rng.sample(other, 2)
            add(f"S{idx:03}", o, d, rng.choice(PROFILES)[0], rng.randint(0, 120), rng.randint(6, 40), rng.randint(5, 30), rng.randint(30000, 160000), rng.randint(800, 4000))
        conn.execute(schedules.insert(), rows)
        docs = []
        for i, name, _, _, description in PROFILES:
            for section in range(5):
                docs.append(dict(id=f"profile-{i}-{section+1}", carrier_id=i, document_type="carrier_profile", version=1,
                    text=f"SYNTHETIC. {name}. {description} Service note {section+1}: schedules, capacity and eligibility must be verified in the structured network."))
        for index, cap in enumerate(["fragile", "secure", "refrigerated", "hazmat"]):
            docs.append(dict(id=f"handling-{cap}", carrier_id=None, document_type="handling_guidance", version=1,
                text=f"SYNTHETIC authored guidance: {cap} cargo requires an explicit {cap} capability flag. Each transfer requires the hub buffer. Descriptive similarity does not establish eligibility."))
            docs.append(dict(id=f"case-{index+1:03}", carrier_id=None, document_type="planning_case", version=1,
                text=f"SYNTHETIC planning case: {cap} cargo was routed only on verified {cap} carriers. Compare capacity and deadlines; minimize transfers only after the requested primary objective."))
        conn.execute(documents.insert(), docs)
