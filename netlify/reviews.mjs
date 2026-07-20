/**
 * reviews.mjs
 * ===========
 * Stores and serves reviews.
 *
 * HOW THE STORAGE WORKS:
 * Netlify Blobs is a small key-value store built into Netlify - no database to
 * set up, no extra service. We keep two keys:
 *
 *   "latest"   the 10 newest reviews, shown on the site
 *   "archive"  every review ever left, kept but not displayed
 *
 * When an 11th review arrives, the oldest drops out of "latest" and moves to
 * "archive". Nothing is ever deleted - you can download the archive any time
 * with ?archive=1.
 *
 * GET  /api/reviews            -> the 10 shown reviews
 * GET  /api/reviews?archive=1  -> everything, ever
 * POST /api/reviews            -> add one, returns the updated 10
 */

import { getStore } from "@netlify/blobs";

const SHOWN = 10;          // how many appear on the site
const MAX_NAME = 40;
const MAX_TEXT = 300;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** Read a key, returning a fallback if it's missing or unreadable. */
async function read(store, key, fallback) {
  try {
    const value = await store.get(key, { type: "json" });
    return Array.isArray(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Strip anything that could break the page or be used to attack it.
 * The frontend also escapes on display, but cleaning on the way IN means bad
 * data never reaches storage in the first place.
 */
function clean(text, limit) {
  return String(text || "")
    .replace(/<[^>]*>/g, "")     // no HTML tags
    .replace(/\s+/g, " ")        // collapse whitespace and newlines
    .trim()
    .slice(0, limit);
}

export default async (request) => {
  const store = getStore("docmind-reviews");
  const url = new URL(request.url);

  // ---- READ ----
  if (request.method === "GET") {
    if (url.searchParams.get("archive")) {
      const archive = await read(store, "archive", []);
      const latest = await read(store, "latest", []);
      // The archive holds the ones that scrolled off; add the current ten so
      // the download is genuinely everything.
      return json({ reviews: [...latest, ...archive], total: latest.length + archive.length });
    }

    return json({ reviews: await read(store, "latest", []) });
  }

  // ---- WRITE ----
  if (request.method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "Bad request." }, 400);
    }

    const name = clean(body.name, MAX_NAME);
    const text = clean(body.review, MAX_TEXT);

    if (!name || !text) return json({ error: "Please fill in both fields." }, 400);
    if (text.length < 4) return json({ error: "That review is a bit short." }, 400);

    const latest = await read(store, "latest", []);

    // Basic duplicate guard: the same person posting the same words twice is
    // almost always a double-click or a bot.
    if (latest.some((r) => r.who === name && r.text === text)) {
      return json({ reviews: latest, duplicate: true });
    }

    const entry = { text, who: name, at: new Date().toISOString() };
    const updated = [entry, ...latest];

    // Anything past the tenth moves to the archive rather than disappearing.
    if (updated.length > SHOWN) {
      const pushedOut = updated.splice(SHOWN);
      const archive = await read(store, "archive", []);
      await store.setJSON("archive", [...pushedOut, ...archive]);
    }

    await store.setJSON("latest", updated);
    return json({ reviews: updated });
  }

  return new Response("Method not allowed", { status: 405 });
};

export const config = { path: "/api/reviews" };
