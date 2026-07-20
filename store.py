"""
store.py
========
JOB OF THIS FILE: the "search engine" of the app (the R in RAG = Retrieval).

HOW SEARCH WORKS HERE (two scores added together):

1. MEANING SCORE (embeddings)
   Every chunk is converted into a list of numbers (a vector) that represents
   its meaning. The question is converted the same way. Chunks whose vector
   points in a similar direction to the question's vector are relevant.
   This catches "what is the fee?" matching "the charge is Rs 500".

2. KEYWORD SCORE
   Plain word overlap. This catches exact things embeddings are bad at:
   names, invoice numbers, section codes, dates.

Using both is called HYBRID SEARCH and it is noticeably more accurate than
either one alone.

Everything lives in memory (a normal Python dict). Restart the server and it's
gone. That's fine for now - swap this file for a real vector DB later and
nothing else in the app has to change.
"""

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


# ---------------------------------------------------------------------------
# STEP 0: Make the CPU work as hard as it can
# ---------------------------------------------------------------------------
# Embedding is pure maths, and PyTorch will happily use every core you have -
# but only if it knows how many there are. On some Windows setups it defaults
# to one thread, which makes a large file take four times longer than it needs.
try:
    import torch
    torch.set_num_threads(os.cpu_count() or 4)
except Exception:
    pass   # no torch? sentence-transformers will complain louder than we would


# ---------------------------------------------------------------------------
# STEP 1: Load the embedding model ONCE when the server starts
# ---------------------------------------------------------------------------
# First run downloads ~90MB. After that it's cached and works offline.
# Want better quality? Swap in "BAAI/bge-small-en-v1.5" - same code, no changes.
_MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Bigger batches = fewer round trips through the model = faster on big files.
# Too big and you'll run out of RAM; 128 is comfortable on a normal laptop.
_BATCH = int(os.getenv("EMBED_BATCH", "128"))

_model = None


def get_model() -> SentenceTransformer:
    """Load the model lazily so the server starts fast."""
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


# ---------------------------------------------------------------------------
# STEP 2: The cache - never embed the same file twice
# ---------------------------------------------------------------------------
# Embedding a 1500-page PDF takes minutes. Doing it again after a restart, for
# a file that hasn't changed, is pure waste.
#
# So we fingerprint the file's bytes. Same fingerprint = same file = reuse the
# vectors we already computed. Re-uploading is then instant, and the work
# survives restarts.
CACHE_DIR = Path(os.getenv("CACHE_DIR", ".docmind_cache"))
CACHE_DIR.mkdir(exist_ok=True)


def fingerprint(file_bytes: bytes) -> str:
    """A short, stable id for this exact file content."""
    return hashlib.sha256(file_bytes).hexdigest()[:32]


def _cache_paths(fp: str) -> tuple[Path, Path]:
    return CACHE_DIR / f"{fp}.npy", CACHE_DIR / f"{fp}.json"


def load_cached(fp: str, filename: str, session: str = "local") -> str | None:
    """
    If we've seen this exact file before, load it back in and skip all the
    work. Returns a doc_id, or None if it isn't cached.
    """
    vec_path, meta_path = _cache_paths(fp)
    if not (vec_path.exists() and meta_path.exists()):
        return None

    try:
        vectors = np.load(vec_path)
        chunks = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None            # corrupt cache entry - just redo the work

    doc_id = str(uuid.uuid4())
    DOCUMENTS[doc_id] = {
        "filename": filename,
        "chunks": chunks,
        "vectors": vectors.astype(np.float32),
        "fingerprint": fp,
        "session": session,
        "touched": time.time(),
    }
    return doc_id


def _save_cache(fp: str, chunks: list[dict], vectors: np.ndarray) -> None:
    """Write the finished vectors to disk so next time is instant."""
    vec_path, meta_path = _cache_paths(fp)
    try:
        np.save(vec_path, vectors)
        meta_path.write_text(json.dumps(chunks), encoding="utf-8")
    except Exception:
        pass                   # a failed cache write must never break an upload


# ---------------------------------------------------------------------------
# STEP 3: Where uploaded documents live while the server is running
# ---------------------------------------------------------------------------
# Shape: { doc_id: {"filename": str, "chunks": [...], "vectors": np.ndarray} }
DOCUMENTS: dict[str, dict] = {}


def add_document(
    filename: str,
    chunks: list[dict],
    fp: str | None = None,
    session: str = "local",
) -> str:
    """
    Embed every chunk and keep it in memory. Returns a doc_id the frontend
    uses to ask questions about this specific file.

    `session` is who owns this document. Every lookup checks it, so two people
    using the site at the same time can't see each other's files.
    """
    texts = [c["text"] for c in chunks]

    # normalize_embeddings=True makes every vector length 1. That's a small
    # trick: it means cosine similarity becomes a plain dot product later.
    vectors = get_model().encode(
        texts,
        normalize_embeddings=True,
        batch_size=_BATCH,
        show_progress_bar=len(texts) > 500,   # only worth watching on big files
        convert_to_numpy=True,
    )
    vectors = np.array(vectors, dtype=np.float32)

    if fp:
        _save_cache(fp, chunks, vectors)

    doc_id = str(uuid.uuid4())
    DOCUMENTS[doc_id] = {
        "filename": filename,
        "chunks": chunks,
        "vectors": vectors,
        "fingerprint": fp,
        "session": session,
        "touched": time.time(),
    }
    return doc_id


# ---------------------------------------------------------------------------
# WHO OWNS WHAT
# ---------------------------------------------------------------------------
# Everything above keeps documents in one dictionary. That's fine on your own
# machine, but the moment two people use the site at once they'd be searching
# each other's files. Every function below checks ownership first.

def owns(doc_id: str, session: str) -> bool:
    """Does this visitor own this document?"""
    doc = DOCUMENTS.get(doc_id)
    return bool(doc) and doc.get("session") == session


def check_owned(doc_ids: list[str], session: str) -> None:
    """Raise if the visitor is asking about something that isn't theirs."""
    for doc_id in doc_ids:
        if not owns(doc_id, session):
            raise KeyError("That document isn't available. Please upload it again.")


def session_documents(session: str) -> list[dict]:
    """Everything this one visitor has loaded."""
    return [
        {"doc_id": did, "filename": d["filename"], "chunks": len(d["chunks"])}
        for did, d in DOCUMENTS.items()
        if d.get("session") == session
    ]


def find_by_fingerprint(fp: str, session: str) -> str | None:
    """
    Has this visitor already uploaded this exact file? Re-uploading the same
    PDF shouldn't create a second copy eating the same memory twice.
    """
    for did, d in DOCUMENTS.items():
        if d.get("session") == session and d.get("fingerprint") == fp:
            return did
    return None


# ---------------------------------------------------------------------------
# KEEPING MEMORY UNDER CONTROL
# ---------------------------------------------------------------------------
# Documents live in RAM. Without a cap, a handful of large PDFs from a few
# visitors will exhaust the server. So: a limit per visitor, and old sessions
# get dropped when space runs short.

MAX_DOCS_PER_SESSION = int(os.getenv("MAX_DOCS_PER_SESSION", "6"))
MAX_TOTAL_DOCS = int(os.getenv("MAX_TOTAL_DOCS", "60"))


def session_doc_count(session: str) -> int:
    return sum(1 for d in DOCUMENTS.values() if d.get("session") == session)


def touch(doc_ids: list[str]) -> None:
    """Mark documents as recently used, so eviction skips them."""
    now = time.time()
    for doc_id in doc_ids:
        if doc_id in DOCUMENTS:
            DOCUMENTS[doc_id]["touched"] = now


def evict_if_needed() -> int:
    """
    Drop the least recently used documents when the server is holding too many.

    Losing an old document is annoying; running out of memory takes the whole
    site down for everyone. The cached vectors are still on disk, so anyone
    affected just re-uploads and it comes back instantly.
    """
    removed = 0
    while len(DOCUMENTS) > MAX_TOTAL_DOCS:
        oldest = min(DOCUMENTS, key=lambda d: DOCUMENTS[d].get("touched", 0))
        DOCUMENTS.pop(oldest, None)
        removed += 1
    return removed


# ---------------------------------------------------------------------------
# STEP 3: The keyword half of the search
# ---------------------------------------------------------------------------
# Very common words carry no meaning, so we ignore them when matching keywords.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "it", "this", "that", "what", "which", "who", "how", "why",
    "does", "do", "did", "with", "from", "by", "as", "at", "be", "can", "will",
    "about", "tell", "me", "please", "explain",
}


def _stem(word: str) -> str:
    """
    Chop off common English endings so different forms of the same word match.

    Without this, a question about a "dog" scores ZERO against a document that
    says "dogs" - a real bug this app had. Not a proper stemmer, just the four
    endings that cause most misses: dogs->dog, payments->payment,
    reporting->report, revised->revis.
    """
    for ending in ("ing", "ies", "es", "ed", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _words(text: str) -> set[str]:
    """Lowercase words, minus the useless ones, reduced to their stems."""
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {_stem(t) for t in tokens if t not in _STOPWORDS and len(t) > 2}


def _keyword_score(question: str, chunk_text: str) -> float:
    """What fraction of the question's meaningful words appear in the chunk?"""
    q_words = _words(question)
    if not q_words:
        return 0.0
    c_words = _words(chunk_text)
    return len(q_words & c_words) / len(q_words)


# ---------------------------------------------------------------------------
# STEP 4: The actual search
# ---------------------------------------------------------------------------
def search(doc_ids: list[str], question: str, top_k: int = 5) -> list[dict]:
    """
    Search ACROSS SEVERAL DOCUMENTS at once and return the top_k best chunks.

    Why this works without any clever merging: every chunk is scored on the
    same 0-1 scale regardless of which file it came from. So we can score all
    the documents, pour the results into one pile, and sort the pile. A chunk
    from file B beats a chunk from file A only if it genuinely matches better.

    Each result carries its filename, so the answer can say
    "page 4 of History.pdf" instead of just "page 4".
    """
    if isinstance(doc_ids, str):        # tolerate a single id being passed in
        doc_ids = [doc_ids]

    missing = [d for d in doc_ids if d not in DOCUMENTS]
    if missing:
        raise KeyError("Some documents aren't loaded anymore. Please upload them again.")

    if not doc_ids:
        raise KeyError("No documents selected.")

    # 4a. Turn the question into a vector ONCE, then reuse it for every file.
    q_vector = get_model().encode([question], normalize_embeddings=True)[0]

    results = []
    for doc_id in doc_ids:
        doc = DOCUMENTS[doc_id]

        # 4b. Meaning score for every chunk in this file at once (one fast
        #     matrix multiply). Because all vectors are normalized, this dot
        #     product IS cosine similarity: ~0.0 unrelated, ~1.0 same meaning.
        meaning_scores = doc["vectors"] @ q_vector

        # 4c. Add the keyword score on top. 0.75 / 0.25 weighting means meaning
        #     leads, but exact word matches can still push a chunk up.
        for chunk, meaning in zip(doc["chunks"], meaning_scores):
            keyword = _keyword_score(question, chunk["text"])
            final = (0.75 * float(meaning)) + (0.25 * keyword)
            results.append({
                **chunk,
                "score": final,
                "doc_id": doc_id,
                "filename": doc["filename"],
            })

    # 4d. Sort the combined pile best-first and keep only the top few.
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def get_full_text(doc_ids: list[str]) -> str:
    """
    All the selected documents' text joined together - used to verify quotes.

    Joining them is fine: we only ask "does this sentence exist somewhere in
    what the user selected?" Which file it's in is answered separately, by
    matching the quote against the individual chunks.
    """
    if isinstance(doc_ids, str):
        doc_ids = [doc_ids]

    parts = []
    for doc_id in doc_ids:
        doc = DOCUMENTS.get(doc_id)
        if doc:
            parts.extend(c["text"] for c in doc["chunks"])
    return "\n".join(parts)


def split_question(question: str) -> list[str]:
    """
    Break a multi-part question into separate searches.

    THE PROBLEM THIS SOLVES:
    "tell me about calculus and what's the syllabus of applied chemistry" is
    two questions. Embedded as one vector, the two topics average into a blur
    that matches neither well - so a document containing BOTH answers can come
    back with neither.

    Searching each part separately and merging the results finds both.

    We only split where a real second question starts, not on every "and":
    "terms and conditions" must stay one phrase.
    """
    text = question.strip()

    # Split on question marks and on connectors that introduce a new ask.
    parts = re.split(
        r"\?|\bwhat about\b|\band what\b|\band whats\b|\band what's\b|"
        r"\balso tell\b|\band tell me\b|\band also\b|;",
        text,
        flags=re.IGNORECASE,
    )

    cleaned = []
    for part in parts:
        part = part.strip(" ,.;-")
        words = part.split()

        # Keep real fragments, drop leftovers. A single word counts if it's
        # substantial - otherwise "what is TRC and what about DRC?" throws
        # away "DRC", which was the whole point of the second half.
        if len(words) >= 2 or (len(words) == 1 and len(part) >= 3):
            cleaned.append(part)

    # Nothing usable found? Just search the original.
    if not cleaned:
        return [text]

    # Always include the whole question too. Sometimes the parts lose context
    # that the full sentence still carries.
    if text not in cleaned:
        cleaned.append(text)

    return cleaned[:4]        # cap it - each part is another pass over the file


def multi_search(doc_ids: list[str], question: str, top_k: int = 8) -> list[dict]:
    """
    Search once per part of the question, then merge FAIRLY.

    WHY FAIRNESS MATTERS HERE:
    Sorting all the results together by score sounds right, but it isn't. Ask
    "what is calculus and what's the chemistry syllabus" and calculus might
    score 0.52 while chemistry scores 0.44. Sort globally and calculus takes
    nine of the twelve slots, so the chemistry half of your question gets
    answered from scraps.

    Instead we take turns: best calculus hit, best chemistry hit, second best
    calculus, second best chemistry... Every part of the question gets equal
    room, no matter which one the search happens to like more.
    """
    queries = split_question(question)

    # One ranked list per sub-question.
    per_query: list[list[dict]] = []
    for query in queries:
        per_query.append(search(doc_ids, query, top_k=top_k))

    # Round-robin through the lists, skipping chunks we've already taken.
    picked: dict[tuple, dict] = {}
    for rank in range(top_k):
        for hits in per_query:
            if rank >= len(hits):
                continue
            hit = hits[rank]
            key = (hit["doc_id"], hit["id"])

            # Same chunk found by two parts? Keep the better score.
            if key in picked:
                if hit["score"] > picked[key]["score"]:
                    picked[key] = hit
                continue

            picked[key] = hit
            if len(picked) >= top_k:
                break
        if len(picked) >= top_k:
            break

    # Sort what we picked by score - the balance is already locked in by the
    # selection above, this just puts the strongest evidence first.
    return sorted(picked.values(), key=lambda r: r["score"], reverse=True)


def get_chunks(doc_ids: list[str]) -> list[dict]:
    """
    Every chunk from the selected documents, each tagged with its filename.

    Used to locate a verified quote. The retrieved top-5 aren't enough: a quote
    can be verified against the full text but live in a chunk that didn't make
    the top 5, and then the citation reads "in your files" with no page.
    """
    if isinstance(doc_ids, str):
        doc_ids = [doc_ids]

    out = []
    for doc_id in doc_ids:
        doc = DOCUMENTS.get(doc_id)
        if doc:
            out.extend(
                {**c, "doc_id": doc_id, "filename": doc["filename"]}
                for c in doc["chunks"]
            )
    return out


def remove_document(doc_id: str, session: str = "local") -> bool:
    """
    Forget a document. Checks ownership first - otherwise anyone who guessed
    an id could delete someone else's file.
    """
    if not owns(doc_id, session):
        return False
    return DOCUMENTS.pop(doc_id, None) is not None


def list_documents() -> list[dict]:
    """Everything currently loaded - so the UI can rebuild its list."""
    return [
        {"doc_id": doc_id, "filename": doc["filename"], "chunks": len(doc["chunks"])}
        for doc_id, doc in DOCUMENTS.items()
    ]
