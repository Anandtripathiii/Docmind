/**
 * ask.mjs
 * =======
 * THE ONLY PART THAT RUNS ON A SERVER.
 *
 * Everything else - reading your PDF, cutting it up, searching it - happens in
 * your browser. This function exists for one reason: your API key must never
 * be sent to a browser, so the call to Gemini has to happen somewhere private.
 *
 * WHAT IT RECEIVES: a question, plus the handful of text sections the browser
 * already decided were relevant.
 * WHAT IT SENDS BACK: an answer whose quotes have been checked against those
 * sections. Any quote the model invented is deleted before you see it.
 *
 * This is the same anti-hallucination idea as the Python version, just moved.
 */

const MODEL = process.env.GEMINI_MODEL || "gemini-flash-latest";
const VERSION = process.env.GEMINI_API_VERSION || "v1beta";

const SYSTEM_PROMPT = `You answer questions about a document the user uploaded.

HARD RULES:
1. When the question is about the document, every factual statement in your
   answer must come from the EXCERPTS provided. No outside knowledge, no
   filling gaps, no reasonable guesses.
2. If the excerpts only partly cover the question, say exactly what they do
   cover and state plainly what is missing.
3. If the excerpts do not cover it at all, set "source" to "general", answer
   from your own knowledge, and say the document doesn't discuss it.
4. Every string in "quotes" must be copied CHARACTER FOR CHARACTER from the
   excerpts. Quotes that don't match are deleted automatically.
5. Never mention "excerpts" or "context" in the answer text.
6. If the question asks several things, answer EVERY part with equal depth,
   each in its own paragraph.

Reply with ONLY a JSON object:
{
  "source": "document" | "partial" | "general",
  "answer": "the direct answer",
  "explain": "plain-English explanation of what it means and where it came from",
  "missing": "what the document does NOT say, or empty string",
  "quotes": ["exact sentence from the excerpts"],
  "confidence": "high" | "medium" | "low"
}`;

/* ---------------------------------------------------------------------------
   Quote verification - the heart of the app.
   Strip everything except letters and numbers, then check the quote really
   appears in the text we sent. A quote the model made up won't be found, so
   it gets thrown away.
--------------------------------------------------------------------------- */
const normalize = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function verifyQuotes(quotes, haystack) {
  if (!Array.isArray(quotes)) return [];
  const hay = normalize(haystack);
  return quotes
    .filter((q) => typeof q === "string" && q.trim().length >= 15)
    .filter((q) => hay.includes(normalize(q)))
    .map((q) => q.trim());
}

/** Which file and page did each surviving quote come from? */
function locateQuotes(quotes, chunks) {
  return quotes.map((q) => {
    const needle = normalize(q);
    const hit = chunks.find((c) => normalize(c.text).includes(needle));
    return hit
      ? { filename: hit.filename || "", page: hit.page || 0 }
      : { filename: "", page: 0 };
  });
}

/** Models sometimes wrap JSON in ``` fences or add a chatty preamble. */
function parseJson(text) {
  const cleaned = text.trim().replace(/^```(?:json)?|```$/gm, "").trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      try { return JSON.parse(match[0]); } catch { /* fall through */ }
    }
  }
  return {
    source: "general",
    answer: "The answer came back in a format I couldn't read. Please ask again.",
    explain: "", missing: "", quotes: [], confidence: "low",
  };
}

export default async (request) => {
  if (request.method !== "POST") {
    return new Response("Use POST", { status: 405 });
  }

  const key = process.env.GEMINI_API_KEY;
  if (!key) {
    return json({ error: "GEMINI_API_KEY isn't set in this site's environment variables." }, 500);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Bad request." }, 400);
  }

  const question = (body.question || "").trim();
  const chunks = Array.isArray(body.chunks) ? body.chunks.slice(0, 14) : [];
  const history = Array.isArray(body.history) ? body.history.slice(-2) : [];

  if (!question) return json({ error: "Ask a question first." }, 400);
  if (!chunks.length) return json({ error: "No document sections were sent." }, 400);

  // Guard the payload size. A browser could otherwise post a whole book and
  // blow past both the function timeout and the model's input limit.
  const excerpts = chunks
    .map((c) => `[${c.filename || "document"} - page ${c.page}]\n${(c.text || "").slice(0, 2500)}`)
    .join("\n\n");

  const recap = history.length
    ? "EARLIER IN THIS CONVERSATION:\n" +
      history.map((t) => `Q: ${t.question}\nA: ${(t.answer || "").slice(0, 200)}`).join("\n") +
      "\n\n"
    : "";

  const weak = !chunks.some((c) => (c.score ?? 1) >= 0.30);
  const note = weak
    ? 'NOTE: nothing matched this question well. Unless the excerpts genuinely answer it, use source="general".\n\n'
    : "";

  const userMessage =
    `${note}${recap}EXCERPTS FROM THE USER'S DOCUMENTS:\n` +
    `-----------------------------------\n${excerpts}\n` +
    `-----------------------------------\n\nQUESTION: ${question}`;

  // --- call Gemini -------------------------------------------------------
  let data;
  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/${VERSION}/models/${MODEL}:generateContent`,
      {
        method: "POST",
        headers: { "x-goog-api-key": key, "Content-Type": "application/json" },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
          contents: [{ role: "user", parts: [{ text: userMessage }] }],
          generationConfig: {
            temperature: 0,
            responseMimeType: "application/json",
            maxOutputTokens: 4096,
          },
        }),
      }
    );

    if (res.status === 429) return json({ error: "Free tier limit reached. Try again in a minute." }, 429);
    if (res.status === 404) return json({ error: `Model "${MODEL}" not found. Set GEMINI_MODEL in Netlify.` }, 502);

    if (!res.ok) {
      // Show WHAT Gemini objected to. A bare status number tells you nothing -
      // you can't tell a bad model name from a malformed request from a
      // blocked key. The response body says exactly which it is.
      let why = "";
      try {
        const body = await res.json();
        why = body?.error?.message || "";
      } catch {
        why = (await res.text().catch(() => "")).slice(0, 200);
      }
      return json({ error: `Gemini ${res.status}: ${why || "no detail given"}` }, 502);
    }

    data = await res.json();
  } catch (err) {
    return json({ error: "Couldn't reach Gemini." }, 502);
  }

  // Newer models return their "thinking" as a separate part. Skip those parts,
  // or we'd try to parse the reasoning as JSON and fail.
  const parts = data?.candidates?.[0]?.content?.parts || [];
  const text = parts.filter((p) => !p.thought).map((p) => p.text || "").join("").trim();

  if (!text) {
    const reason = data?.candidates?.[0]?.finishReason || "unknown";
    return json({ error: `Gemini returned nothing (${reason}).` }, 502);
  }

  const result = parseJson(text);

  // THE CHECK: only quotes that really exist survive.
  const haystack = chunks.map((c) => c.text).join("\n");
  result.quotes = verifyQuotes(result.quotes, haystack);
  result.sources = locateQuotes(result.quotes, chunks);

  // No verified quote to back a document claim? Say so instead of hiding it.
  if (["document", "partial"].includes(result.source) && !result.quotes.length) {
    result.confidence = "low";
  }

  result.evidence = chunks.map((c) => ({
    filename: c.filename, page: c.page,
    text: (c.text || "").slice(0, 400),
    score: Math.round((c.score ?? 0) * 1000) / 1000,
  }));

  return json(result);
};

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export const config = { path: "/api/ask" };
