from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CAPABILITIES = {"fragile", "secure", "refrigerated", "hazmat"}


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str | None = None
    destination: str | None = None
    pallets: int | None = Field(default=None, gt=0, le=1000)
    max_budget_cents: int | None = Field(default=None, ge=0)
    ready_at: datetime | None = None
    delivery_deadline: datetime | None = None
    optimization_goal: Literal["cheapest", "fastest"] = "cheapest"
    max_stops: int = Field(default=2, ge=0, le=2)
    min_on_time_rate: float | None = Field(default=None, ge=0, le=1)
    required_capabilities: list[str] = Field(default_factory=list, max_length=4)
    minimal_handling: bool = False
    prefer_direct: bool = False
    transfer_savings_threshold_cents: int | None = Field(default=None, ge=0)

    @field_validator("ready_at", "delivery_deadline")
    @classmethod
    def aware_dates(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamps must include a timezone, e.g. 2026-11-01T06:00:00Z")
            return value.astimezone(timezone.utc)
        return value

    @field_validator("required_capabilities")
    @classmethod
    def known_capabilities(cls, value):
        if set(value) - CAPABILITIES:
            raise ValueError("Supported capabilities: fragile, secure, refrigerated, hazmat")
        return sorted(set(value))

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.ready_at and self.delivery_deadline and self.delivery_deadline < self.ready_at:
            raise ValueError("Delivery deadline must be on or after ready_at")
        return self


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=100)
    # Explicit fields override language extraction and let users resolve ambiguities.
    constraints: Constraints | None = None


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="", max_length=4000)
    constraints: Constraints | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.message.strip() and self.constraints is None:
            raise ValueError("Supply an answer or structured constraints")
        return self
