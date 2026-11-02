import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, event, select)
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """PostgreSQL TIMESTAMPTZ, with equivalent UTC ISO strings at our boundary."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite returns naive values from DateTime.
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

metadata = MetaData()
hubs = Table("hubs", metadata,
    Column("id", String, primary_key=True), Column("name", String, nullable=False),
    Column("timezone", String, nullable=False), Column("aliases", Text, nullable=False),
    Column("connection_minutes", Integer, nullable=False), Column("transfer_cents", Integer, nullable=False))
carriers = Table("carriers", metadata,
    Column("id", String, primary_key=True), Column("name", String, nullable=False),
    Column("on_time_rate", Float, nullable=False), CheckConstraint("on_time_rate >= 0 AND on_time_rate <= 1"))
capabilities = Table("carrier_capabilities", metadata,
    Column("carrier_id", ForeignKey("carriers.id"), primary_key=True),
    Column("capability", String, primary_key=True), Column("enabled", Boolean, nullable=False))
schedules = Table("schedules", metadata,
    Column("id", String, primary_key=True),
    Column("origin", ForeignKey("hubs.id"), nullable=False, index=True),
    Column("destination", ForeignKey("hubs.id"), nullable=False),
    Column("carrier_id", ForeignKey("carriers.id"), nullable=False),
    Column("departure_at", UTCDateTime, nullable=False, index=True),
    Column("arrival_at", UTCDateTime, nullable=False),
    Column("capacity_pallets", Integer, nullable=False),
    Column("base_cost_cents", Integer, nullable=False), Column("per_pallet_cents", Integer, nullable=False),
    CheckConstraint("origin <> destination"), CheckConstraint("arrival_at > departure_at"),
    CheckConstraint("capacity_pallets >= 0"), CheckConstraint("base_cost_cents >= 0 AND per_pallet_cents >= 0"))
requests = Table("shipment_requests", metadata,
    Column("id", String, primary_key=True), Column("conversation_id", String, index=True),
    Column("state_json", Text, nullable=False))
documents = Table("documents", metadata,
    Column("id", String, primary_key=True), Column("carrier_id", ForeignKey("carriers.id")),
    Column("document_type", String, nullable=False), Column("text", Text, nullable=False),
    Column("version", Integer, nullable=False))


# Additive table: create_all adds it to existing installations without rewriting records.
# Logical IDs group revisions of ONE passage; distinct sections must have distinct IDs.
document_reviews = Table("document_reviews", metadata,
    Column("source_id", ForeignKey("documents.id"), primary_key=True),
    Column("logical_id", String, nullable=False),
    Column("effective_from", UTCDateTime), Column("effective_until", UTCDateTime),
    Column("claims_json", Text, nullable=False, default="{}"),
    CheckConstraint("effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from"))


class Database:
    def __init__(self, url=None):
        data = Path(os.getenv("DATA_DIR", ".data"))
        data.mkdir(parents=True, exist_ok=True)
        url = url or os.getenv("DATABASE_URL", f"sqlite:///{data / 'routemind.db'}")
        self.engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def configure_sqlite(conn, _):
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=10000")
        metadata.create_all(self.engine)

    def all(self, table):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(table)).mappings()]

    def network(self):
        hs = {r["id"]: r for r in self.all(hubs)}
        cs = {r["id"]: r for r in self.all(carriers)}
        for c in cs.values():
            c["capabilities"] = []
        for r in self.all(capabilities):
            if r["enabled"]:
                cs[r["carrier_id"]]["capabilities"].append(r["capability"])
        return hs, cs, self.all(schedules)

    def save(self, state):
        with self.engine.begin() as conn:
            values = {"conversation_id": state.get("conversation_id"), "state_json": json.dumps(state)}
            # Request IDs are UUIDs; updates only occur under the API's per-request lock.
            if conn.execute(select(requests.c.id).where(requests.c.id == state["request_id"])).first():
                conn.execute(requests.update().where(requests.c.id == state["request_id"]).values(**values))
            else:
                conn.execute(requests.insert().values(id=state["request_id"], **values))

    def load(self, request_id):
        with self.engine.connect() as conn:
            value = conn.execute(select(requests.c.state_json).where(requests.c.id == request_id)).scalar_one_or_none()
        return json.loads(value) if value else None
