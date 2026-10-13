// The live agent's server when the demo is hosted on Render (render.yaml). Same rules as the Netlify
// function it wraps (netlify/functions/agent.mjs): fixed system prompt and tools, request validation, a
// per-visitor and a daily limit, and the API key only in the ANTHROPIC_API_KEY environment variable.
//
// Differences from Netlify: the usage counters live in memory, so they reset when the service restarts
// (a free Render service sleeps after 15 idle minutes), and requests are accepted only from the page's
// own origins (ALLOWED_ORIGINS).
import http from "node:http";
import { validate, buildRequest } from "./netlify/functions/agent.mjs";

const PORT = Number(process.env.PORT || 8787);
const MODEL_URL = (process.env.ANTHROPIC_BASE_URL || "https://api.anthropic.com").replace(/\/+$/, "") + "/v1/messages";
const DAILY_LIMIT = Number(process.env.DAILY_LIMIT || 1200);
const VISITOR_LIMIT = Number(process.env.VISITOR_LIMIT || 150);
const ORIGINS = (process.env.ALLOWED_ORIGINS || "https://lineassist-app.onrender.com,https://lineassist-app.netlify.app").split(",").map(s => s.trim());
const MAX_BODY = 200_000;

const counts = new Map();
function limited(ip) {
  const day = new Date().toISOString().slice(0, 10);
  for (const k of counts.keys()) if (!k.startsWith(day)) counts.delete(k);
  const total = counts.get(`${day}/all`) || 0, mine = counts.get(`${day}/${ip}`) || 0;
  if (total >= DAILY_LIMIT) return "The demo has reached its limit for today. The recorded calls still work, and the live agent is back tomorrow.";
  if (mine >= VISITOR_LIMIT) return "You have reached today's limit for the live agent. The recorded calls still work.";
  counts.set(`${day}/all`, total + 1); counts.set(`${day}/${ip}`, mine + 1);
  return null;
}

function send(res, status, body, origin) {
  res.writeHead(status, {
    "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff",
    ...(origin ? { "access-control-allow-origin": origin, vary: "Origin" } : {}),
  });
  res.end(JSON.stringify(body));
}

http.createServer(async (req, res) => {
  const origin = ORIGINS.includes(req.headers.origin) ? req.headers.origin : null;
  if (req.url === "/health") return send(res, 200, { ok: true });
  if (req.method === "OPTIONS") {
    res.writeHead(origin ? 204 : 403, origin ? { "access-control-allow-origin": origin, "access-control-allow-methods": "POST",
      "access-control-allow-headers": "content-type", "access-control-max-age": "600", vary: "Origin" } : {});
    return res.end();
  }
  if (req.url !== "/api/agent") return send(res, 404, { error: "not found" });
  if (req.method !== "POST") return send(res, 405, { error: "POST only" }, origin);
  if (!origin) return send(res, 403, { error: "This endpoint only serves the LineAssist demo page." });
  if (!process.env.ANTHROPIC_API_KEY) return send(res, 503, { error: "The live agent is not configured on this site." }, origin);

  let raw = "";
  for await (const chunk of req) { raw += chunk; if (raw.length > MAX_BODY) return send(res, 413, { error: "too large" }, origin); }
  let body;
  try { body = JSON.parse(raw); } catch { return send(res, 400, { error: "bad json" }, origin); }
  const problem = validate(body);
  if (problem) return send(res, 400, { error: problem }, origin);
  const ip = String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "unknown").split(",")[0].trim();
  const stop = limited(ip);
  if (stop) return send(res, 429, { error: stop }, origin);

  try {
    const r = await fetch(MODEL_URL, {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" },
      body: JSON.stringify(buildRequest(body)),
    });
    if (!r.ok) {
      const detail = await r.text();
      console.error("model error", r.status, detail.slice(0, 500));
      return send(res, 502, { error: r.status === 429 || r.status === 529 ? "The model is busy. Try again in a moment." : "The model returned an error. Try again." }, origin);
    }
    const out = await r.json();
    return send(res, 200, { content: out.content, stop_reason: out.stop_reason, usage: out.usage }, origin);
  } catch (e) {
    console.error("model unreachable", e);
    return send(res, 502, { error: "The model could not be reached. Try again." }, origin);
  }
}).listen(PORT, () => console.log(`lineassist api on :${PORT}`));
