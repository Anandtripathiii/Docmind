/**
 * embed.mjs
 * =========
 * Turns text into vectors, so search can match by MEANING and not just by
 * matching words. "What's the fee?" should find "the charge is Rs 500".
 *
 * WHY THIS IS A SERVER FUNCTION AND NOT BROWSER CODE:
 * same reason as ask.mjs - the API key can't be handed to a browser.
 *
 * The vectors come straight back to the browser, which keeps them in memory
 * and does the actual searching itself. Nothing is stored on any server, so
 * your documents never leave your machine except as these excerpts.
 *
 * IF THIS FAILS, NOTHING BREAKS. The frontend falls back to keyword-only
 * search, which is worse but perfectly usable. Meaning-search is an upgrade,
 * not a requirement.
 */

// Google renames embedding models fairly often, and a name that works on one
// account 404s on another. Rather than guess once and fail, try each in turn.
const MODELS = process.env.EMBED_MODEL
  ? [process.env.EMBED_MODEL]
  : ["gemini-embedding-001", "text-embedding-004", "embedding-001"];
const VERSION = process.env.GEMINI_API_VERSION || "v1beta";

// Gemini accepts a batch of texts per call. Keeping batches modest keeps us
// well inside the function's time limit.
const MAX_BATCH = 100;

export default async (request) => {
  if (request.method !== "POST") return new Response("Use POST", { status: 405 });

  const key = process.env.GEMINI_API_KEY;
  if (!key) return json({ error: "GEMINI_API_KEY isn't set." }, 500);

  let body;
  try { body = await request.json(); } catch { return json({ error: "Bad request." }, 400); }

  const texts = Array.isArray(body.texts) ? body.texts.slice(0, MAX_BATCH) : [];
  if (!texts.length) return json({ error: "No texts sent." }, 400);

  // A query and a document should be embedded slightly differently - the model
  // is told which role the text is playing so the two match up better.
  const taskType = body.isQuery ? "RETRIEVAL_QUERY" : "RETRIEVAL_DOCUMENT";

  const problems = [];

  for (const model of MODELS) {
    try {
      const res = await fetch(
        `https://generativelanguage.googleapis.com/${VERSION}/models/${model}:batchEmbedContents`,
        {
          method: "POST",
          headers: { "x-goog-api-key": key, "Content-Type": "application/json" },
          body: JSON.stringify({
            requests: texts.map((t) => ({
              model: `models/${model}`,
              content: { parts: [{ text: String(t).slice(0, 8000) }] },
              taskType,
            })),
          }),
        }
      );

      if (res.ok) {
        const data = await res.json();
        const vectors = (data.embeddings || []).map((e) => e.values);
        if (vectors.length) return json({ vectors, model });
        problems.push(`${model}: empty response`);
        continue;
      }

      // Record why this one failed and try the next name.
      let why = "";
      try { why = (await res.json())?.error?.message || ""; } catch { /* ignore */ }
      problems.push(`${model}: ${res.status} ${why.slice(0, 120)}`);

    } catch (err) {
      problems.push(`${model}: ${err.message}`);
    }
  }

  // Every name failed. Say which and why - the frontend falls back to keyword
  // search either way, but now you can see what to fix.
  return json({ error: "Embedding unavailable", detail: problems.join(" | ") }, 502);
};

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

export const config = { path: "/api/embed" };
