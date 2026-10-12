// The only server-side code in the demo. It forwards a conversation to the model with a
// fixed system prompt and fixed tools, and returns the model's reply.
//
// What it will not do, so that a public page cannot be used as a free model endpoint:
//   - accept a system prompt, a model name or tool definitions from the browser
//   - answer more than a set number of requests per visitor or per day
//   - run if the usage counter cannot be read (it fails closed)
// The API key lives in the ANTHROPIC_API_KEY environment variable and never reaches the page.
import { getStore } from "@netlify/blobs";
import { SYSTEM, REVIEW_SYSTEM, TOOLS } from "../lib/prompt.mjs";

const MODEL = "claude-haiku-4-5-20251001";
const DAILY_LIMIT = Number(process.env.DAILY_LIMIT || 1200);       // model calls per day, all visitors
const VISITOR_LIMIT = Number(process.env.VISITOR_LIMIT || 150);    // model calls per day, one visitor
const MAX_MESSAGES = 160, MAX_CHARS = 90000, MAX_NOTES_CHARS = 3000;

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

export function validate(body) {
  if (!body || !["agent", "review"].includes(body.mode)) return "bad mode";
  const m = body.messages;
  if (!Array.isArray(m) || m.length === 0 || m.length > MAX_MESSAGES) return "bad messages";
  if (m[0].role !== "user") return "conversation must start with the customer";
  for (const x of m) {
    if (!x || !["user", "assistant"].includes(x.role)) return "bad role";
    if (typeof x.content !== "string" && !Array.isArray(x.content)) return "bad content";
    if (Array.isArray(x.content)) for (const b of x.content) {
      if (!b || !["text", "tool_use", "tool_result"].includes(b.type)) return "bad block";
    }
  }
  if (JSON.stringify(m).length > MAX_CHARS) return "conversation too long";
  if (body.notes !== undefined && (typeof body.notes !== "string" || body.notes.length > MAX_NOTES_CHARS)) return "bad notes";
  return null;
}

async function countAndCheck(ip) {
  const store = getStore("usage");
  const day = new Date().toISOString().slice(0, 10);
  const keys = [`day/${day}`, `visitor/${day}/${ip}`];
  const [total, mine] = await Promise.all(keys.map(async k => Number(await store.get(k)) || 0));
  if (total >= DAILY_LIMIT) return "The demo has reached its limit for today. The recorded calls still work, and the live agent is back tomorrow.";
  if (mine >= VISITOR_LIMIT) return "You have reached today's limit for the live agent. The recorded calls still work.";
  await Promise.all([store.set(keys[0], String(total + 1)), store.set(keys[1], String(mine + 1))]);
  return null;
}

export function buildRequest(body) {
  const cached = { type: "ephemeral" };
  if (body.mode === "review") {
    return { model: MODEL, max_tokens: 700, temperature: 0, system: [{ type: "text", text: REVIEW_SYSTEM, cache_control: cached }], messages: body.messages };
  }
  const system = [{ type: "text", text: SYSTEM, cache_control: cached }];
  if (body.notes) system.push({ type: "text", text: `<supervisor_notes>\n${body.notes}\n</supervisor_notes>` });
  // Cache the conversation so far as well: mark the last block of the last message.
  const messages = body.messages.map(m => ({ role: m.role, content: m.content }));
  const last = messages[messages.length - 1];
  if (typeof last.content === "string") last.content = [{ type: "text", text: last.content, cache_control: cached }];
  else last.content = last.content.map((b, i, a) => (i === a.length - 1 ? { ...b, cache_control: cached } : b));
  return { model: MODEL, max_tokens: 1024, temperature: 0, system, tools: TOOLS, messages };
}

export default async (req, context) => {
  if (req.method !== "POST") return json(405, { error: "POST only" });
  if (!process.env.ANTHROPIC_API_KEY) return json(503, { error: "The live agent is not configured on this site." });
  let body;
  try { body = await req.json(); } catch { return json(400, { error: "bad json" }); }
  const problem = validate(body);
  if (problem) return json(400, { error: problem });

  let limited;
  try { limited = await countAndCheck(context?.ip || "unknown"); }
  catch { return json(503, { error: "The live agent is unavailable right now. The recorded calls still work." }); }
  if (limited) return json(429, { error: limited });

  // On Netlify, an AI gateway may supply its own key and address; otherwise call the API directly.
  const base = (process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com").replace(/\/+$/, "");
  const r = await fetch(`${base}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" },
    body: JSON.stringify(buildRequest(body)),
  });
  if (!r.ok) {
    const detail = await r.text();
    console.error("model error", r.status, detail.slice(0, 500));
    let kind = "";
    try { const e = JSON.parse(detail).error; kind = `${e.type}: ${String(e.message).slice(0, 160)}`; } catch {}
    return json(502, { error: r.status === 429 || r.status === 529 ? "The model is busy. Try again in a moment." : "The model returned an error. Try again.", detail: kind });
  }
  const out = await r.json();
  return json(200, { content: out.content, stop_reason: out.stop_reason, usage: out.usage });
};

export const config = { path: "/api/agent" };
