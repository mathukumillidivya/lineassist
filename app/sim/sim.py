"""Runs the benchmark's telecom simulator (account system and phone) for the live demo.

The account tools, phone tools and data models are the benchmark's own files, unmodified.
This module only wires them together the way the benchmark's environment does: after every
action, the phone's surroundings are re-synced with the account (line status, roaming,
data allowance, payment requests).
"""
import json
from datetime import date, datetime

from pydantic import BaseModel

from tau2.domains.telecom.data_model import LineStatus, TelecomDB
from tau2.domains.telecom.tools import TelecomTools
from tau2.domains.telecom.user_data_model import PaymentRequest, TelecomUserDB
from tau2.domains.telecom.user_tools import TelecomUserTools


class Sim:
    def __init__(self, db: dict, user_db: dict, scenario: dict):
        self.tools = TelecomTools(TelecomDB.model_validate(db))
        self.user_tools = TelecomUserTools(TelecomUserDB.model_validate(user_db))
        self.scenario = scenario
        for a in scenario["init"]:
            kit = self.user_tools if a["env_type"] == "user" else self.tools
            getattr(kit, a["func_name"])(**a["arguments"])
            self.sync()

    def sync(self) -> None:
        """Same rules as the benchmark's TelecomEnvironment.sync_tools."""
        s = self.user_tools.db.surroundings
        if s.phone_number is None:
            return
        line = self.tools._get_line_by_phone(s.phone_number)
        s.line_active = line.status == LineStatus.ACTIVE
        s.roaming_allowed = bool(line.roaming_enabled)
        plan = self.tools._get_plan_by_id(line.plan_id)
        s.mobile_data_usage_exceeded = line.data_used_gb >= plan.data_limit_gb + line.data_refueling_gb
        if s.payment_request is not None and s.payment_request.paid:
            self.tools._set_bill_to_paid(s.payment_request.bill_id)
            s.payment_request = None
        if s.payment_request is None:
            customer = self.tools.get_customer_by_phone(s.phone_number)
            bills = self.tools._get_bills_awaiting_payment(customer)
            if bills:
                s.payment_request = PaymentRequest(bill_id=bills[0].bill_id, amount_due=bills[0].total_due)

    def call(self, who: str, name: str, args: dict) -> dict:
        kit = self.user_tools if who == "user" else self.tools
        if "gb_amount" in args:                       # JSON has one number type; the tool expects a float
            args = {**args, "gb_amount": float(args["gb_amount"])}
        try:
            if not kit.has_tool(name):
                raise ValueError(f"Tool '{name}' not found.")
            out, error = kit.use_tool(name, **args), False
            self.sync()
        except Exception as e:  # the benchmark reports tool errors to the caller the same way
            out, error = f"Error: {e}", True
        return {"content": to_text(out), "error": error}

    def status_bar(self) -> str:
        return self.user_tools._check_status_bar()

    def checks(self) -> list:
        """The benchmark's own pass conditions for this scenario, evaluated on the current state."""
        out = []
        for a in self.scenario["assertions"]:
            kit = self.user_tools if a["env_type"] == "user" else self.tools
            try:
                ok = getattr(kit, a["func_name"])(**a["arguments"]) == a["assert_value"]
            except Exception:
                ok = False
            self.sync()
            out.append({"name": a["func_name"], "met": bool(ok)})
        return out


def to_text(resp) -> str:
    def process(r):
        if isinstance(r, BaseModel):
            return r.model_dump()
        if isinstance(r, (list, tuple)):
            return [process(x) for x in r]
        if isinstance(r, dict):
            return {k: process(v) for k, v in r.items()}
        if isinstance(r, (datetime, date)):
            return r.isoformat()
        if isinstance(r, (int, float, bool)) and not isinstance(r, str):
            return str(r)
        return r
    return resp if isinstance(resp, str) else json.dumps(process(resp), default=str)


SIM = None


def start(db_json: str, user_db_json: str, scenario_json: str) -> str:
    global SIM
    SIM = Sim(json.loads(db_json), json.loads(user_db_json), json.loads(scenario_json))
    return SIM.status_bar()


def call(who: str, name: str, args_json: str) -> str:
    r = SIM.call(who, name, json.loads(args_json))
    r["status_bar"] = SIM.status_bar()
    r["checks"] = SIM.checks()
    return json.dumps(r)
