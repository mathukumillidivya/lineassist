// Live call: the visitor is the customer, the phone and account are the benchmark's own
// simulator running in the browser (Python, through Pyodide), and the agent is LineAssist.
// The model is reached through one server function; everything else happens on this page.
(() => {
const PYODIDE = new URLSearchParams(location.search).get("pyodide") || "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const rich = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
const words = n => n.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
const TODAY = "2025-02-25";

// What the customer can do on the phone. Names match the provider's manual, because the agent asks for them by name.
const PHONE = [
  ["Check", [
    ["check_status_bar", "Status bar"], ["check_network_status", "Network status"], ["check_network_mode_preference", "Network mode"],
    ["check_sim_status", "SIM card"], ["check_data_restriction_status", "Data Saver"], ["check_apn_settings", "APN settings"],
    ["check_wifi_calling_status", "Wi-Fi Calling"], ["check_vpn_status", "VPN"],
    ["check_app_permissions", "Messaging app permissions", { app_name: "messaging" }],
    ["run_speed_test", "Run a speed test"], ["can_send_mms", "Try sending a picture message"], ["check_payment_request", "Payment requests"]]],
  ["Change", [
    ["toggle_airplane_mode", "Airplane mode on or off"], ["toggle_data", "Mobile data on or off"], ["toggle_roaming", "Data roaming on or off"],
    ["toggle_data_saver_mode", "Data Saver on or off"], ["toggle_wifi_calling", "Wi-Fi Calling on or off"], ["disconnect_vpn", "Disconnect VPN"],
    ["set_network_mode_preference", "Set network mode to 4G and 5G preferred", { mode: "4g_5g_preferred" }],
    ["reseat_sim_card", "Take the SIM out and put it back"], ["reset_apn_settings", "Reset APN settings"],
    ["grant_app_permission", "Give Messaging the storage permission", { app_name: "messaging", permission: "storage" }],
    ["grant_app_permission", "Give Messaging the SMS permission", { app_name: "messaging", permission: "sms" }],
    ["reboot_device", "Restart the phone"], ["make_payment", "Pay the requested bill"]]],
];
const HANDOFF = /transfer|escalat|specialist|human agent|technician|higher[- ]level|support team|visit (a|our|the) store|unable to (resolve|fix)|beyond what i can/i;
const PHONE_RE = /\b\d{3}[-. ]\d{3}[-. ]\d{4}\b/g;

let py = null, bundle = null, booting = null;
let S = null;           // state of the current call

async function boot() {
  if (booting) return booting;
  booting = (async () => {
    setPhoneNote("Starting the phone. This takes a few seconds the first time.");
    bundle = await (await fetch("sim.json")).json();
    await new Promise((ok, bad) => { const s = document.createElement("script"); s.src = PYODIDE + "pyodide.js"; s.onload = ok; s.onerror = () => bad(new Error("could not load the simulator runtime")); document.head.appendChild(s); });
    const p = await loadPyodide({ indexURL: PYODIDE });
    await p.loadPackage("pydantic");
    for (const [path, src] of Object.entries(bundle.py)) { const f = "/sim/" + path; p.FS.mkdirTree(f.slice(0, f.lastIndexOf("/"))); p.FS.writeFile(f, src); }
    p.runPython("import sys; sys.path.insert(0, '/sim'); import sim");
    py = p.pyimport("sim");
    drawScenarios();
    start(0);
  })().catch(e => { setPhoneNote("The phone simulator could not start (" + e.message + "). The recorded calls still work."); throw e; });
  return booting;
}
const sim = (who, name, args) => JSON.parse(py.call(who, name, JSON.stringify(args || {})));

// ---------- a call
function start(n) {
  const sc = bundle.scenarios[n];
  const bar = py.start(JSON.stringify(bundle.db), JSON.stringify(bundle.user_db), JSON.stringify(sc));
  S = { n, sc, messages: [], notes: [], callerPhone: null, lineIds: [], linePhone: {}, usageChecked: false, contractEnded: [], facts: {},
        blocks: 0, lineBlocks: 0, policyBlocks: 0, reviews: 0, transferred: false, busy: false, ended: false, calls: 0, guardLog: [], bar, checks: [] };
  S.checks = sim("user", "check_status_bar").checks;   // reading the status bar changes nothing
  $("#l-thread").innerHTML = "";
  bubble("a", "Hi! How can I help you today?");
  $("#l-input").value = ""; $("#l-input").placeholder = "Describe your problem to the agent";
  drawScenarios(); drawPhone(null); drawSide(); setBusy(false);
}

// ---------- rendering
function drawScenarios() {
  $("#l-scenarios").innerHTML = bundle.scenarios.map((s, i) => `<button class="scn" aria-pressed="${S && S.n === i}" data-n="${i}"><b>${esc(s.title)}</b><span>${esc(s.blurb)}</span></button>`).join("");
  $("#l-scenarios").querySelectorAll("button").forEach(b => b.onclick = () => { if (!S.busy) start(+b.dataset.n); });
}
function setPhoneNote(t) { $("#l-status").innerHTML = `<em>${esc(t)}</em>`; }
function drawPhone(last) {
  $("#l-status").innerHTML = S.bar.split("|").map(x => `<span>${esc(x.trim())}</span>`).join("");
  $("#l-result").innerHTML = last
    ? `<span class="who-acted">You ran</span><h4>${esc(last.label)}</h4><button class="tell" id="l-tell">Tell the agent what it shows</button><p>${esc(last.text)}</p>`
    : `<h4>Your phone</h4><p class="hint">When the agent asks you to check or change something, find it in the list and tap it. The result appears here.</p>`;
  if (last) $("#l-tell").onclick = () => { $("#l-input").value = `I ran ${last.name}. It shows: ${last.text}`; send(); };
  const asked = S.asked || [];
  $("#l-actions").innerHTML = PHONE.map(([group, rows]) => `<h5>${group}</h5>` + rows.map(([name, label, args], i) =>
    `<button class="row${asked.includes(name) ? " asked" : ""}" data-name="${name}" data-args='${esc(JSON.stringify(args || {}))}' data-label="${esc(label)}"><span>${esc(label)}<small>${name}${asked.includes(name) ? " · the agent asked for this" : ""}</small></span></button>`).join("")).join("");
  $("#l-actions").querySelectorAll("button").forEach(b => b.onclick = () => phoneAction(b.dataset.name, JSON.parse(b.dataset.args), b.dataset.label));
  const first = $("#l-actions .asked"); if (first) $("#l-actions").scrollTop = first.offsetTop - $("#l-actions").offsetTop - 8;
}
function drawSide() {
  const sc = S.sc, done = S.checks.length && S.checks.every(c => c.met);
  const goal = sc.transfer_expected
    ? (S.transferred ? (done ? ["solved", "Correct. The agent transferred you and left the line suspended."] : ["unresolved", "The agent transferred you, but the account is not in the state policy requires."]) : ["wait", "The right outcome is a transfer to a human, with the line left suspended."])
    : (done ? ["solved", "Fixed. Every benchmark check for this call passes."] : S.transferred ? ["handoff", "The agent transferred you with the problem unfixed."] : ["wait", "Not fixed yet."]);
  $("#l-side").innerHTML =
    `<h3>You are the customer</h3><p class="role">${esc(sc.known)} ${esc(sc.reason)}</p>` +
    `<div class="goal ${goal[0]}">${esc(goal[1])}</div>` +
    `<div class="ftable">${S.checks.map(c => `<div class="frow"><span>${esc(sc.check_labels[c.name] || c.name)}</span><span><i class="tick ${c.met ? "on" : "off"}">${c.met ? "✓" : ""}</i></span></div>`).join("")}</div>` +
    `<details class="reveal"><summary>Show what is wrong with this phone</summary><ul>${sc.faults.map(f => `<li>${esc(f)}</li>`).join("")}</ul></details>` +
    `<h3 class="gl">What the guardrails did</h3>` +
    (S.guardLog.length ? `<ul class="glog">${S.guardLog.map(g => `<li><b>${esc(g[0])}</b> ${esc(g[1])}</li>`).join("")}</ul>` : `<p class="role">Nothing yet. Entries appear here when code steps in: a wrong phone line, a transfer that came too early, a rule the agent tried to break.</p>`) +
    `<p class="meter-line">${S.calls} model call${S.calls === 1 ? "" : "s"} so far in this conversation.</p>`;
}
function bubble(k, text) { add(`<div class="msg ${k}"><small>${k === "a" ? "Agent" : "You"}</small>${rich(text)}</div>`); }
function row(cls, html) { add(`<div class="act ${cls}">${html}</div>`); }
function add(html) { const t = $("#l-thread"); t.insertAdjacentHTML("beforeend", html); t.scrollTop = t.scrollHeight; }
function setBusy(b) {
  S.busy = b; $("#l-send").disabled = b || S.ended; $("#l-input").disabled = b || S.ended;
  const old = $("#l-typing"); if (old) old.remove();
  if (b) add(`<div class="act at" id="l-typing">The agent is working…</div>`);
  if (S.ended) $("#l-input").placeholder = "This call has ended. Pick a call to start again.";
}
function guard(kind, text) { S.guardLog.push([kind, text]); row("guardrow", `<b>${esc(kind)}.</b> ${esc(text)}`); drawSide(); }

// ---------- the customer's side
function phoneAction(name, args, label) {
  if (!py || S.busy) return;
  const r = sim("user", name, args);
  S.bar = r.status_bar; S.checks = r.checks;
  row("ct", `You, on the phone <code>${esc(words(name))}</code>`);
  S.asked = (S.asked || []).filter(x => x !== name);
  const body = r.content.replace(/\s*Status Bar:.*$/s, "");
  drawPhone({ name, label, text: body || r.content || "Done." }); drawSide();
}
async function send() {
  const text = $("#l-input").value.trim();
  if (!text || S.busy || S.ended) return;
  $("#l-input").value = "";
  bubble("c", text);
  if (!S.callerPhone) { const f = text.match(PHONE_RE); if (f) S.callerPhone = f[f.length - 1].replace(/[. ]/g, "-"); }
  S.messages.push({ role: "user", content: text });
  setBusy(true);
  try { await agentTurn(); } catch (e) { row("warn", esc(e.message)); }
  setBusy(false); drawSide();
}

// ---------- LineAssist: the same four layers as the benchmarked agent, plus the policy check
async function model(mode, messages, notes) {
  let r;
  try { r = await fetch("/api/agent", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode, messages, notes }) }); }
  catch { throw new Error("The live agent could not be reached. It only runs on the hosted site."); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { console.error("live agent", r.status, body.detail || ""); throw new Error(body.error || "The live agent is unavailable right now."); }
  S.calls++;
  return body.content || [];
}
function caseNote(d) {
  const phone = S.callerPhone;
  if (d.line_id && d.phone_number && phone) {
    if (String(d.phone_number) !== phone) return `This is NOT the customer's line. The customer's number is ${phone}. Ignore these details.`;
    const parts = [`This IS the customer's line (${phone}).`], end = String(d.contract_end_date || ""), ended = end && end < TODAY;
    if (String(d.status || "").toLowerCase() === "suspended") parts.push(ended
      ? `The line is suspended. Its contract ended on ${end}, before today (${TODAY}): it must not be resumed, and the customer has to be transferred once the phone itself has been checked.`
      : "The line is suspended and its contract is still running: look for an overdue bill.");
    parts.push(d.roaming_enabled ? "Roaming is enabled on the line." : "Roaming is NOT enabled on the line: enable it if the customer is abroad.");
    parts.push("That is the account side only. If the customer is abroad, data roaming must also be ON in the phone itself: confirm it with check_network_status.");
    if (!S.usageChecked) parts.push("Data allowance not checked yet: call get_data_usage for this line.");
    return (S.facts.line = parts.join(" "));
  }
  if (d.line_id && "data_limit_gb" in d && "data_used_gb" in d) {
    if (S.linePhone[d.line_id] !== phone) return null;
    const used = +d.data_used_gb, avail = +d.data_limit_gb + (+d.data_refueling_gb || 0);
    if (Number.isNaN(used) || Number.isNaN(avail)) return null;
    S.usageChecked = true;
    return (S.facts.data = used >= avail
      ? `Data allowance used up: ${used} GB used against ${avail} GB available. Mobile data will not work until the customer refuels data or changes plan. Ask how much they want to refuel, confirm the price, then apply exactly that amount.`
      : `Data allowance is fine: ${used} GB used of ${avail} GB available.`);
  }
  return null;
}
function observe(tu, content) {
  if (tu.name === "get_customer_by_phone" && tu.input.phone_number) S.callerPhone = String(tu.input.phone_number);
  let d; try { d = JSON.parse(content); } catch { return null; }
  if (!d || typeof d !== "object" || Array.isArray(d)) return null;
  if (Array.isArray(d.line_ids)) S.lineIds = d.line_ids.map(String);
  if (d.line_id && d.phone_number) {
    S.linePhone[d.line_id] = String(d.phone_number);
    const end = String(d.contract_end_date || "");
    if (end && end < TODAY && !S.contractEnded.includes(d.line_id)) S.contractEnded.push(d.line_id);
  }
  return caseNote(d);
}
function wrongLine(uses) {
  if (!S.callerPhone) return null;
  for (const tu of uses) {
    const line = tu.input.line_id; if (!line) continue;
    const seen = S.linePhone[line]; if (seen === S.callerPhone) continue;
    const left = S.lineIds.filter(x => !(x in S.linePhone)), match = Object.keys(S.linePhone).find(k => S.linePhone[k] === S.callerPhone);
    return { line, tool: tu.name, note: `Line check failed: ${line} ${seen ? `has the number ${seen}.` : "has not been looked up yet."} The customer's number is ${S.callerPhone}. Do not act on or quote details from a line until get_details_by_id shows its phone_number is ${S.callerPhone}.` +
      (match ? ` The matching line is ${match}.` : left.length ? ` Lines not yet looked up: ${left.join(", ")}.` : "") };
  }
  return null;
}
function policyProblem(uses) {
  const tu = uses.find(t => t.name === "resume_line" && S.contractEnded.includes(String(t.input.line_id)));
  return tu ? `Not allowed: the contract for line ${tu.input.line_id} has ended, and policy forbids lifting the suspension on such a line, even after an overdue bill is paid. Finish checking the phone itself, then transfer the customer to a human agent.` : null;
}
function transcript(extra) {
  const out = [];
  for (const m of S.messages.concat(extra)) {
    const who = m.role === "assistant" ? "AGENT" : "CUSTOMER";
    if (typeof m.content === "string") { out.push(`${who}: ${m.content}`); continue; }
    for (const b of m.content) {
      if (b.type === "text" && b.text) out.push(`${who}: ${b.text}`);
      if (b.type === "tool_use") out.push(`AGENT [tool call] ${b.name}(${JSON.stringify(b.input)})`);
      if (b.type === "tool_result") out.push(`[tool result] ${typeof b.content === "string" ? b.content : JSON.stringify(b.content)}`);
    }
  }
  return out.join("\n");
}
async function review(draft) {
  S.reviews++;
  const facts = [`Customer's number: ${S.callerPhone || "not known"}`, S.facts.line || "The customer's line has NOT been identified yet.",
                 S.facts.data || "Data allowance has NOT been checked (get_data_usage on the customer's line)."].join("\n");
  const out = await model("review", [{ role: "user", content: `<conversation>\n${transcript([{ role: "assistant", content: draft }])}\n</conversation>\n\n<computed_facts>\n${facts}\n</computed_facts>\n\nIs the hand-off justified?` }]);
  const text = out.filter(b => b.type === "text").map(b => b.text).join(""), m = text.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try { const v = JSON.parse(m[0]); if (typeof v.allow !== "boolean") return null; v.remaining = (v.remaining || []).map(String).slice(0, 8); return v; } catch { return null; }
}
const blockedNote = v => `Hand-off not approved by the supervisor. ${v.reason || ""}\nBefore this customer can be transferred, do the following, one at a time, and confirm each result:\n${v.remaining.map(x => "- " + x).join("\n")}\nContinue helping the customer now. Do not mention this note or a transfer.`;
const results = (uses, text) => ({ role: "user", content: uses.map(tu => ({ type: "tool_result", tool_use_id: tu.id, content: text })) });

async function agentTurn() {
  for (let step = 0; step < 14; step++) {
    const content = await model("agent", S.messages, S.notes.join("\n\n") || undefined);
    const uses = content.filter(b => b.type === "tool_use"), text = content.filter(b => b.type === "text").map(b => b.text).join("\n").trim();
    const isTransfer = uses.some(t => t.name === "transfer_to_human_agents");

    if (uses.length) {
      const pol = S.policyBlocks < 3 ? policyProblem(uses) : null;
      if (pol) { S.policyBlocks++; S.messages.push({ role: "assistant", content }, results(uses, pol)); guard("Policy check", "The agent tried to reactivate a line whose contract has ended. The call was not made."); continue; }
      const wl = S.lineBlocks < 4 ? wrongLine(uses) : null;
      if (wl) { S.lineBlocks++; S.messages.push({ role: "assistant", content }, results(uses, wl.note)); guard("Line check", `The agent tried to use ${words(wl.tool).toLowerCase()} on ${wl.line}, which is not your line. The call was not made.`); continue; }
      if (isTransfer && S.blocks < 3 && S.reviews < 6) {
        const v = await review(content);
        if (v && !v.allow && v.remaining.length) { S.blocks++; S.messages.push({ role: "assistant", content }, results(uses, blockedNote(v))); guard("Hand-off guard", `The agent tried to transfer you. A reviewer found ${v.remaining.length} check${v.remaining.length === 1 ? "" : "s"} not done yet, so the transfer was withheld.`); continue; }
      }
      if (text) bubble("a", text);
      const out = [];
      for (const tu of uses) {
        const r = sim("assistant", tu.name, tu.input);
        S.bar = r.status_bar; S.checks = r.checks;
        const note = r.error ? null : observe(tu, r.content);
        if (tu.name === "transfer_to_human_agents") { S.transferred = true; row("hand", "The agent transferred you to a human."); }
        else row("at", `Agent, on the account <code>${esc(words(tu.name))}</code>${tu.input.line_id || tu.input.id ? ` <span>${esc(tu.input.line_id || tu.input.id)}</span>` : ""}`);
        out.push({ type: "tool_result", tool_use_id: tu.id, content: note ? `${r.content}\n[case note] ${note}` : r.content });
      }
      S.messages.push({ role: "assistant", content }, { role: "user", content: out });
      drawPhone(null); drawSide();
      const typing = $("#l-typing"); if (typing) $("#l-thread").appendChild(typing);
      continue;
    }

    if (text && !S.transferred && HANDOFF.test(text) && S.blocks < 3 && S.reviews < 6) {
      const v = await review(content);
      if (v && !v.allow && v.remaining.length) { S.blocks++; S.notes.push(blockedNote(v)); guard("Hand-off guard", "The agent was about to tell you it could not fix this. A reviewer found checks not done yet, so the agent was sent back."); continue; }
    }
    S.messages.push({ role: "assistant", content: content.length ? content : [{ type: "text", text: "(no reply)" }] });
    if (text) bubble("a", text);
    S.asked = PHONE.flatMap(g => g[1]).map(r => r[0]).filter((n, i, a) => a.indexOf(n) === i && new RegExp("\\b" + n + "\\b").test(text));
    // The agent sometimes describes a step instead of naming it. Point the visitor at the matching control.
    for (const [re, names] of [[/payment request/i, ["check_payment_request"]], [/(accept|complete|make) (the )?payment|pay (the|your) (overdue )?bill/i, ["make_payment"]],
                               [/\b(restart|reboot)\b/i, ["reboot_device"]]]) if (re.test(text)) for (const n of names) if (!S.asked.includes(n)) S.asked.push(n);
    if (S.transferred) S.ended = true;
    drawPhone(null);
    return;
  }
  row("warn", "The agent took too many steps without replying. Send another message to continue.");
}

$("#l-send").onclick = send;
$("#l-input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
$("#l-restart").onclick = () => { if (S && !S.busy) start(S.n); };
window.LineAssistLive = { boot };
})();
