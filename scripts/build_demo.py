"""Build the public demo page (app/site/index.html) from saved test runs.

The page replays recorded conversations. It makes no API calls and contains no key.
Usage: python scripts/build_demo.py
"""
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = {"base": "test-baseline", "ours": "test-lineassist"}
CUSTOMER_LINE = "L1002"

FAULTS = {
    "airplane_mode_on": "Airplane mode is on",
    "bad_network_preference": "Phone locked to 2G",
    "data_usage_exceeded": "Data allowance used up",
    "data_mode_off": "Mobile data switched off",
    "unseat_sim_card": "SIM card not seated",
    "bad_wifi_calling": "Wi-Fi Calling blocking picture messages",
    "break_apn_mms_setting": "Picture-message server address missing",
    "user_abroad_roaming_disabled_on": "Abroad, roaming not enabled on the account",
    "user_abroad_roaming_disabled_off": "Abroad, roaming off on the account and the phone",
    "user_abroad_roaming_enabled_off": "Abroad, roaming switched off in the phone",
    "data_saver_mode_on": "Data Saver is on",
    "bad_vpn": "Slow VPN connected",
    "break_app_storage_permission": "Messaging app lacks storage permission",
    "break_app_sms_permission": "Messaging app lacks SMS permission",
    "break_app_both_permissions": "Messaging app lacks storage and SMS permissions",
    "break_apn_settings": "Network (APN) settings broken",
    "lock_sim_card_pin": "SIM locked by PIN (only a human can unlock)",
    "overdue_bill_suspension": "Line suspended for an overdue bill",
    "contract_end_suspension": "Line suspended, contract ended (must go to a human)",
}
# Which recorded action counts as the fix for each fault being run (who runs it, tool name, how many times).
FIXES = {
    "airplane_mode_on": [("c", "toggle_airplane_mode", 1)], "bad_network_preference": [("c", "set_network_mode_preference", 1)],
    "data_usage_exceeded": [("a", "refuel_data", 1)], "data_mode_off": [("c", "toggle_data", 1)],
    "unseat_sim_card": [("c", "reseat_sim_card", 1)], "bad_wifi_calling": [("c", "toggle_wifi_calling", 1)],
    "break_apn_mms_setting": [("c", "reset_apn_settings", 1)], "break_apn_settings": [("c", "reset_apn_settings", 1)],
    "user_abroad_roaming_disabled_on": [("a", "enable_roaming", 1)],
    "user_abroad_roaming_disabled_off": [("a", "enable_roaming", 1), ("c", "toggle_roaming", 1)],
    "user_abroad_roaming_enabled_off": [("c", "toggle_roaming", 1)],
    "data_saver_mode_on": [("c", "toggle_data_saver_mode", 1)], "bad_vpn": [("c", "disconnect_vpn", 1)],
    "break_app_storage_permission": [("c", "grant_app_permission", 1)], "break_app_sms_permission": [("c", "grant_app_permission", 1)],
    "break_app_both_permissions": [("c", "grant_app_permission", 2)],
    "lock_sim_card_pin": [("a", "transfer_to_human_agents", 1)], "contract_end_suspension": [("a", "transfer_to_human_agents", 1)],
    "overdue_bill_suspension": [("a", "resume_line", 1)],
}


def fix_steps(steps: list[dict], faults: list[str]) -> list:
    """For each fault, the step at which its fix had been run (None if it never was).
    Agent actions count only when they were made on the customer's own line."""
    out = []
    for f in faults:
        latest = -1
        for who, tool, times in FIXES[f]:
            hits = [i for i, s in enumerate(steps) if s["k"] == who + "t" and s["n"] == tool and not s.get("flag")]
            if len(hits) < times:
                latest = None
                break
            latest = max(latest, hits[times - 1])
        out.append(latest)
    return out


ISSUES = {"service_issue": "No service", "mobile_data_issue": "Mobile data", "mms_issue": "Picture messages"}
CHECKS = {
    "assert_service_status": "Phone service is in the correct state", "assert_mobile_data_status": "Mobile data works",
    "assert_internet_speed": "Speed test is excellent", "assert_can_send_mms": "Picture messages send",
    "assert_data_refueling_amount": "Correct data top-up applied", "assert_no_overdue_bill": "No overdue bill left",
}


def clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n].rstrip() + " …"


def outcome_of(sim: dict) -> str:
    ri = sim["reward_info"]
    expected = [a["action"]["name"] for a in ri.get("action_checks") or []]
    calls = [tc["name"] for m in sim["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    handed = "transfer_to_human_agents" in calls or (sim["messages"][-1].get("content") or "").strip().endswith("###TRANSFER###")
    if ri["reward"] >= 1 - 1e-6:
        return "solved"
    return "handoff" if handed and "transfer_to_human_agents" not in expected else "unresolved"


def conversation(sim: dict, fault_keys: list[str]) -> dict:
    results = {m["id"]: m for m in sim["messages"] if m["role"] == "tool"}
    steps = []
    for m in sim["messages"]:
        if m["role"] == "tool":
            continue
        who = "a" if m["role"] == "assistant" else "c"
        first = len(steps)
        text = (m.get("content") or "").replace("###STOP###", "").replace("###TRANSFER###", "").strip()
        if text:
            steps.append({"k": who, "t": clip(text, 900)})
        for tc in m.get("tool_calls") or []:
            res = results.get(tc["id"], {})
            args = tc.get("arguments") or {}
            step = {"k": who + "t", "n": tc["name"], "a": ", ".join(f"{k}={v}" for k, v in args.items() if k != "summary"),
                    "r": clip(res.get("content") or "", 420)}
            bar = re.search(r"Status Bar: (.+)", res.get("content") or "")
            if bar:
                step["sb"] = bar.group(1).strip()
            line = args.get("line_id") or (args.get("id") if str(args.get("id", "")).startswith("L") else None)
            if who == "a" and line and line != CUSTOMER_LINE and tc["name"] != "get_details_by_id":
                step["flag"] = f"This is line {line}. The customer's line is {CUSTOMER_LINE}."
            if tc["name"] == "transfer_to_human_agents":
                step["flag2"] = "Handed to a human"
                step["r"] = clip(args.get("summary", ""), 420)
            steps.append(step)
        # Tokens for this model call (agent side only), on the first step it produced.
        usage = (m.get("raw_data") or {}).get("usage") if who == "a" else None
        if usage and len(steps) > first:
            steps[first]["u"] = [usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), usage.get("cache_read_input_tokens") or 0]
    ri = sim["reward_info"]
    expected = [a["action"]["name"] for a in ri.get("action_checks") or []]
    agent_calls = [tc["name"] for m in sim["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    handed = "transfer_to_human_agents" in agent_calls or (sim["messages"][-1].get("content") or "").strip().endswith("###TRANSFER###")
    passed = ri["reward"] >= 1 - 1e-6
    outcome = ("solved" if passed else
               "handoff" if handed and "transfer_to_human_agents" not in expected else "unresolved")
    return {
        "outcome": outcome, "steps": steps, "fixed": fix_steps(steps, fault_keys),
        "checks": [[CHECKS.get(e["env_assertion"]["func_name"], e["env_assertion"]["func_name"]), bool(e["met"])]
                   for e in ri.get("env_assertions") or []],
        "missed": sorted({a["action"]["name"] for a in ri.get("action_checks") or [] if not a["action_match"]}),
        "cost": round((sim.get("agent_cost") or 0) + (sim.get("user_cost") or 0), 3),
        "agent_cost": round(sim.get("agent_cost") or 0, 4),
        "secs": round(sim.get("duration") or 0),
        "handoff_expected": "transfer_to_human_agents" in expected,
    }


def main() -> None:
    sims = {k: json.loads(gzip.open(ROOT / "results/runs" / v / "results.json.gz").read())["simulations"]
            for k, v in RUNS.items()}
    tasks = {}
    for agent, rows in sims.items():
        for s in rows:
            name = s["task_id"]
            t = tasks.setdefault(name, {
                "issue": ISSUES[re.match(r"\[(\w+)\]", name).group(1)],
                "persona": re.search(r"PERSONA:(\w+)", name).group(1),
                "faults": [FAULTS[f] for f in name.split("]")[1].split("[")[0].split("|")],
                "base": {"pass": 0, "n": 0, "trials": []}, "ours": {"pass": 0, "n": 0, "trials": []}})
            keys = name.split("]")[1].split("[")[0].split("|")
            t[agent]["trials"].append(outcome_of(s))
            t[agent]["n"] += 1
            t[agent]["pass"] += s["reward_info"]["reward"] >= 1 - 1e-6
            if s.get("trial") == 0:
                t[agent]["call"] = conversation(s, keys)
    ordered = sorted(tasks.values(), key=lambda t: (-(t["ours"]["pass"] - t["base"]["pass"]), -len(t["faults"])))
    for i, t in enumerate(ordered):
        t["id"] = i
    data = {"tasks": ordered, "comparison": json.loads((ROOT / "results/test_comparison.json").read_text())}
    extra = ROOT / "results/extra_evals.json"
    if extra.exists():  # evaluations added after the held-out test, reported separately
        data["extra"] = {sec: {k: ({kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v) for k, v in d.items()}
                         for sec, d in json.loads(extra.read_text()).items()}
    html = (ROOT / "app/template.html").read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    # Version the script URL so a browser never pairs a new page with an old cached live.js.
    live = hashlib.sha256((ROOT / "app/site/live.js").read_bytes()).hexdigest()[:10]
    html = html.replace('<script src="live.js"></script>', f'<script src="live.js?v={live}"></script>')
    out = ROOT / "app/site/index.html"
    out.write_text(html)
    print(f"{out} written: {len(ordered)} tasks, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
