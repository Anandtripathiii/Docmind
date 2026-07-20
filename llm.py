"""
llm.py
======
JOB OF THIS FILE: turn the chunks we found into a clear, honest answer.

THREE PROVIDERS, ONE FILE. Pick yours in .env with LLM_PROVIDER=

    gemini     FREE. Needs a key from aistudio.google.com. No credit card.
    ollama     FREE and fully offline. No key at all. Runs on your own PC.
    anthropic  Paid. Best quality.

Switching providers changes ONE LINE in .env. No other file in the app knows
or cares which one you picked.

WHY PLAIN HTTP INSTEAD OF EACH COMPANY'S SDK:
Every provider's SDK has its own install, its own version quirks, and breaks in
its own way when they update it. All three of these are just a POST request with
JSON. Using `requests` for all three means one dependency, and you can read
exactly what is being sent.

------------------------------------------------------------------------------
THE ANTI-HALLUCINATION IDEA (unchanged - this is the heart of the app):

The AI is NOT the source of truth. It only gets the question and the exact text
pulled from the user's file, and it must copy the lines it used.

Then we CHECK those copied lines against the real document in Python. A "quote"
that isn't actually in the file gets deleted. So the AI cannot invent a source,
because inventing one gets it thrown away.

This matters MORE on free models, not less. Smaller models drift from the text
more often - the verifier is what keeps their answers trustworthy.
------------------------------------------------------------------------------
"""

import json
import os
import re

import requests

# ---------------------------------------------------------------------------
# SETTINGS - all read from your .env file
# ---------------------------------------------------------------------------
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Google serves more than one API version and they don't all carry the same
# models. If you get a 404, run probe_gemini.py - it finds the combination
# that works with your key and tells you what to put here.
GEMINI_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# If the best chunk scores below this, the document probably doesn't cover the
# question. Raise it to be stricter, lower it to be more willing to answer.
RELEVANCE_FLOOR = 0.30

TIMEOUT = 90  # seconds. Local models on a slow laptop genuinely need this long.


# ---------------------------------------------------------------------------
# STEP 1: The rules we give the AI
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You answer questions about a document the user uploaded.

HARD RULES:
1. When the question is about the document, every factual statement in your
   answer must come from the EXCERPTS provided. No outside knowledge, no
   filling gaps, no reasonable guesses.
2. If the excerpts only partly cover the question, say exactly what they do
   cover and state plainly what is missing. Partial and honest beats complete
   and invented.
3. If the excerpts do not cover it at all, set "source" to "general", answer
   from your own knowledge, and say the document doesn't discuss it.
4. Every string in "quotes" must be copied CHARACTER FOR CHARACTER from the
   excerpts. Do not tidy, shorten, or rephrase them. Quotes that don't match
   the document exactly are deleted automatically.
5. Never mention "chunks", "excerpts", "context" or "embeddings" in the answer
   text. The user just sees their document.
6. If the question asks several things, answer EVERY part, each with the same
   depth as if it had been asked alone. Give each part its own paragraph. Never
   answer one part well and wave the other away in a sentence.

Reply with ONLY a JSON object, no markdown fences, in this exact shape:
{
  "source": "document" | "partial" | "general",
  "answer": "the direct answer, 1-4 short paragraphs",
  "explain": "plain-English explanation of what this means and where in the document it comes from, for someone who hasn't read it",
  "missing": "what the document does NOT say about this, or empty string",
  "quotes": ["exact sentence from the excerpts", "another exact sentence"],
  "confidence": "high" | "medium" | "low"
}"""


# ---------------------------------------------------------------------------
# STEP 2: Build the message we send
# ---------------------------------------------------------------------------
def _build_user_message(
    question: str,
    chunks: list[dict],
    weak_match: bool,
    history: list[dict] | None = None,
) -> str:
    """Lay the excerpts out with file + page labels so the AI can cite them."""

    if not chunks or weak_match:
        note = (
            "NOTE: nothing in the documents matched this question well. "
            "Unless the excerpts below genuinely answer it, use source=\"general\".\n\n"
        )
    else:
        note = ""

    # With several files loaded, "page 4" is ambiguous - say which file.
    excerpt_text = "\n\n".join(
        f"[{c.get('filename', 'document')} - page {c['page']}]\n{c['text']}"
        for c in chunks
    )

    # A short recap of the conversation, so the answer can flow naturally
    # instead of repeating things you were just told.
    recap = ""
    if history:
        lines = "\n".join(
            f"Q: {t.get('question','')}\nA: {t.get('answer','')[:200]}"
            for t in history[-2:]
        )
        recap = f"EARLIER IN THIS CONVERSATION:\n{lines}\n\n"

    return (
        f"{note}{recap}"
        f"EXCERPTS FROM THE USER'S DOCUMENTS:\n"
        f"-----------------------------------\n{excerpt_text}\n"
        f"-----------------------------------\n\n"
        f"QUESTION: {question}"
    )


# ---------------------------------------------------------------------------
# STEP 3: The three providers. Each takes the same two strings and returns raw
#         text. That shared shape is what makes them swappable.
# ---------------------------------------------------------------------------

def _call_gemini(system: str, user: str, want_json: bool = True) -> str:
    """FREE tier. Get a key at aistudio.google.com - no credit card needed."""
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing from your .env file.")

    url = (
        f"https://generativelanguage.googleapis.com/{GEMINI_VERSION}"
        f"/models/{GEMINI_MODEL}:generateContent"
    )

    # want_json=False is used for the follow-up rewrite, which should come back
    # as a plain sentence. Forcing JSON there made the model reply
    # {"rewritten_question": "..."} and that whole blob leaked into the UI.
    config = {
        "temperature": 0,          # 0 = stick to the text, don't invent
        "maxOutputTokens": 4096,   # thinking models need room before answering
    }
    if want_json:
        config["responseMimeType"] = "application/json"

    response = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        },
        timeout=TIMEOUT,
    )

    # 429 = free requests used up for now. Say so in plain words.
    if response.status_code == 429:
        raise RuntimeError("Free tier limit reached. Wait a minute and try again.")

    # 404 = this model doesn't exist on this API version for this key.
    if response.status_code == 404:
        raise RuntimeError(
            f"Model '{GEMINI_MODEL}' not found on {GEMINI_VERSION}. "
            f"Run 'python probe_gemini.py' to find a combination that works."
        )
    response.raise_for_status()

    data = response.json()

    # ------------------------------------------------------------------
    # READING THE REPLY - trickier than it looks.
    #
    # Newer Gemini models "think" before answering, and the thinking comes
    # back as its OWN part in the list, marked with "thought": true.
    #
    #   parts = [ {"thought": true, "text": "let me see..."},
    #             {"text": "{\"source\": ...}"} ]
    #
    # Grabbing parts[0] gets the thinking instead of the answer, and the JSON
    # parse fails. So: skip thought parts, join whatever text is left.
    # ------------------------------------------------------------------
    candidates = data.get("candidates", [])
    if not candidates:
        # Usually means the prompt was blocked by a safety filter.
        reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini returned no answer (reason: {reason}).")

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])

    text = "".join(
        part.get("text", "")
        for part in parts
        if not part.get("thought")          # <- skip the model's reasoning
    ).strip()

    if not text:
        # An empty answer is almost always the model running out of room
        # mid-thought. Say that plainly instead of "couldn't read the format".
        finish = candidate.get("finishReason", "unknown")
        if finish == "MAX_TOKENS":
            raise RuntimeError(
                "The model used up its response budget while thinking and "
                "returned nothing. Try gemini-flash-lite-latest in your .env, "
                "or ask a shorter question."
            )
        raise RuntimeError(f"Gemini returned an empty answer (finishReason: {finish}).")

    return text


def _call_ollama(system: str, user: str, want_json: bool = True) -> str:
    """
    FREE and fully offline. Install Ollama, then: ollama pull llama3.2
    No key, no internet, no limits - your own computer does the work.
    """
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            **({"format": "json"} if want_json else {}),   # JSON only when asked
            "options": {"temperature": 0},
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def _call_anthropic(system: str, user: str, want_json: bool = True) -> str:
    """Paid, but the most reliable at following the 'copy exactly' rule."""
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is missing from your .env file.")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1200,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    blocks = response.json()["content"]
    return "".join(b.get("text", "") for b in blocks)


# The lookup table that makes swapping providers a one-line change.
_PROVIDERS = {
    "gemini": _call_gemini,
    "ollama": _call_ollama,
    "anthropic": _call_anthropic,
}


# ---------------------------------------------------------------------------
# FOLLOW-UP QUESTIONS
#
# THE PROBLEM: you ask "what is an LLM?" then "how is it trained?".
# Searching for "how is it trained" finds nothing - the document never says
# "it". The search has no idea what you're pointing at.
#
# THE FIX: before searching, rewrite the follow-up into a standalone question
# using what was asked before. "how is it trained?" becomes "how is a Large
# Language Model trained?" - and THAT searches perfectly.
#
# We don't rewrite every question, because that would double the API calls for
# no reason. We only rewrite when a question LOOKS like a follow-up.
# ---------------------------------------------------------------------------

# Words that point at something said earlier instead of naming it.
_POINTING_WORDS = {
    "it", "its", "this", "that", "these", "those", "they", "them", "their",
    "he", "she", "him", "her", "one", "ones", "there",
}

# Openers that almost always continue a previous thought.
_CONTINUERS = ("and ", "what about", "how about", "why", "how come", "then ", "also ")


def looks_like_followup(question: str) -> bool:
    """
    Cheap guess: does this question depend on the previous one?

    Two signals:
      1. It uses a pointing word ("it", "that", "they") - classic follow-up.
      2. It's very short and starts with a continuer ("and why?", "what about
         training?") - too little on its own to search with.

    Being wrong is cheap either way: a needless rewrite still produces a valid
    question, and a missed one just searches slightly worse.
    """
    text = question.lower().strip()
    words = re.findall(r"[a-z']+", text)

    if any(w in _POINTING_WORDS for w in words):
        return True

    if len(words) <= 6 and text.startswith(_CONTINUERS):
        return True

    return False


REWRITE_PROMPT = """Rewrite the user's latest question so it makes sense on its own,
without the conversation.

Replace words like "it", "that", "they" with what they actually refer to.
Keep it short. Change nothing else. Do not answer the question.

Reply with ONLY the rewritten question, no quotes, no explanation."""


def rewrite_followup(question: str, history: list[dict]) -> str:
    """
    Turn a follow-up into a standalone question. Returns the original
    unchanged if there's no history or anything goes wrong - a failed rewrite
    should never block an answer.
    """
    if not history or not looks_like_followup(question):
        return question

    # Only the last few turns matter. More context = slower and more confusing.
    recent = history[-3:]
    conversation = "\n".join(
        f"Q: {turn.get('question', '')}\nA: {turn.get('answer', '')[:300]}"
        for turn in recent
    )

    call = _PROVIDERS.get(PROVIDER)
    if call is None:
        return question

    try:
        rewritten = call(
            REWRITE_PROMPT,
            f"CONVERSATION SO FAR:\n{conversation}\n\nLATEST QUESTION: {question}",
            want_json=False,        # we want a sentence back, not a JSON object
        ).strip().strip('"')

        # Belt and braces: if a model ignores that and returns JSON anyway,
        # dig the question out instead of showing the user raw braces.
        if rewritten.startswith("{"):
            try:
                blob = json.loads(rewritten)
                rewritten = next(
                    (v for v in blob.values() if isinstance(v, str) and v.strip()),
                    question,
                )
            except json.JSONDecodeError:
                return question

        # Sanity check: if the model rambled or returned nothing useful, keep
        # the original. A 200-character "question" is not a question.
        if not rewritten or len(rewritten) > 200:
            return question

        return rewritten

    except Exception:
        return question   # never let the rewrite break the actual answer


# ---------------------------------------------------------------------------
# STEP 4: The one function the rest of the app calls
# ---------------------------------------------------------------------------
def answer_question(
    question: str,
    chunks: list[dict],
    full_text: str,
    history: list[dict] | None = None,
    all_chunks: list[dict] | None = None,
) -> dict:
    """Returns the finished, verified answer dict that the frontend renders."""

    top_score = chunks[0]["score"] if chunks else 0.0
    weak_match = top_score < RELEVANCE_FLOOR

    call = _PROVIDERS.get(PROVIDER)
    if call is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{PROVIDER}'. Use gemini, ollama, or anthropic."
        )

    raw_text = call(
        SYSTEM_PROMPT,
        _build_user_message(question, chunks, weak_match, history),
    )
    result = _parse_json(raw_text)

    # STEP 5: verify the quotes against the real documents (the important bit).
    result["quotes"] = _verify_quotes(result.get("quotes", []), full_text)

    # STEP 6: if the AI claimed the documents said something but left us with
    # no verified quote to prove it, drop the confidence. Don't hide that.
    if result.get("source") in ("document", "partial") and not result["quotes"]:
        result["confidence"] = "low"

    # Locate each quote in EVERY chunk of the selected files, not just the
    # five we retrieved - otherwise a valid quote shows no page number.
    result["sources"] = _sources_for_quotes(result["quotes"], all_chunks or chunks)
    result["top_score"] = round(float(top_score), 3)
    result["provider"] = PROVIDER
    return result


# ---------------------------------------------------------------------------
# Helper: read the JSON even if the model wraps it in ```json fences
# ---------------------------------------------------------------------------
def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...} block. Smaller free models
        # sometimes add a sentence before the JSON despite being told not to.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    # If it's still unreadable, fail honestly rather than showing garbage.
    return {
        "source": "general",
        "answer": "The answer came back in a format I couldn't read. Please ask again.",
        "explain": "",
        "missing": "",
        "quotes": [],
        "confidence": "low",
    }


# ---------------------------------------------------------------------------
# Helper: does this quote REALLY exist in the document?
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Ignore spacing and punctuation differences when comparing."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _verify_quotes(quotes, full_text: str) -> list[str]:
    """Keep only quotes that actually appear in the document."""
    if not isinstance(quotes, list):
        return []                      # a confused model may return a bare string

    haystack = _normalize(full_text)
    verified = []

    for quote in quotes:
        if not isinstance(quote, str) or len(quote.strip()) < 15:
            continue                   # too short to be meaningful evidence
        if _normalize(quote) in haystack:
            verified.append(quote.strip())

    return verified


def _sources_for_quotes(quotes: list[str], chunks: list[dict]) -> list[dict]:
    """
    Find WHICH FILE and which page each verified quote sits on.

    With several documents loaded, "page 4" on its own is useless - you need
    to know page 4 of what.
    """
    sources = []
    for quote in quotes:
        needle = _normalize(quote)
        for chunk in chunks:
            if needle in _normalize(chunk["text"]):
                sources.append({
                    "filename": chunk.get("filename", "document"),
                    "page": chunk["page"],
                })
                break
        else:
            # Verified against the full text, but we couldn't pin the chunk.
            sources.append({"filename": "", "page": 0})
    return sources
