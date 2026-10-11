// Sends two real requests through the same request builder the server function uses, to confirm
// the model accepts them: one agent turn (must come back as a tool call or a question) and one review.
// Run in CI with ANTHROPIC_API_KEY set. Costs well under a cent.
import { buildRequest, validate } from "../netlify/functions/agent.mjs";

async function ask(body) {
  const bad = validate(body);
  if (bad) throw new Error("validate: " + bad);
  const r = await fetch("https://api.anthropic.com/v1/messages", { method: "POST",
    headers: { "content-type": "application/json", "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" },
    body: JSON.stringify(buildRequest(body)) });
  const out = await r.json();
  if (!r.ok) throw new Error(`${r.status} ${JSON.stringify(out).slice(0, 400)}`);
  return out;
}
const first = await ask({ mode: "agent", messages: [{ role: "user", content: "Hi, my mobile data is not working. My number is 555-123-2002 and I am in France." }] });
console.log("agent turn:", first.stop_reason, first.content.map(b => b.type === "tool_use" ? `${b.name}(${JSON.stringify(b.input)})` : b.text.slice(0, 80)), first.usage);
const tu = first.content.find(b => b.type === "tool_use");
if (tu) {
  const second = await ask({ mode: "agent", notes: "Example supervisor note.", messages: [
    { role: "user", content: "Hi, my mobile data is not working. My number is 555-123-2002 and I am in France." },
    { role: "assistant", content: first.content },
    { role: "user", content: [{ type: "tool_result", tool_use_id: tu.id, content: '{"customer_id": "C1001", "line_ids": ["L1001", "L1002", "L1003"]}' }] }] });
  console.log("after a tool result:", second.stop_reason, second.content.map(b => b.type === "tool_use" ? b.name : "text"), second.usage);
}
const review = await ask({ mode: "review", messages: [{ role: "user", content: "<conversation>\nCUSTOMER: My data is slow.\nAGENT [tool call] transfer_to_human_agents({})\n</conversation>\n\n<computed_facts>\nThe customer's line has NOT been identified yet.\n</computed_facts>\n\nIs the hand-off justified?" }] });
const verdict = JSON.parse(review.content[0].text.match(/\{[\s\S]*\}/)[0]);
if (verdict.allow !== false) throw new Error("review should refuse this hand-off");
console.log("review:", verdict);
