"""
app.py
======
JOB OF THIS FILE: the web server. It wires the other files together.

THE WHOLE FLOW IN ONE PLACE:

    upload  ->  reader.py   (file  -> text + page numbers)
            ->  chunker.py  (text  -> small chunks)
            ->  store.py    (chunks -> vectors, kept in memory)

    ask     ->  store.py    (question -> the 5 most relevant chunks)
            ->  llm.py      (chunks -> answer, then quotes verified)
            ->  browser     (answer + evidence shown to the user)

Run it with:   uvicorn app:app --reload
Then open:     http://127.0.0.1:8000
"""

from dotenv import load_dotenv
load_dotenv()  # must run BEFORE importing llm.py, so the API key is available

import os
import time
import uuid

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import chunker
import llm
import reader
import store

app = FastAPI(title="DocMind")

# Serve the CSS/JS/HTML sitting in the static folder.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Reject files bigger than this so one huge upload can't freeze the server.
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "25"))

# ---------------------------------------------------------------------------
# WHO IS THIS? (sessions)
# ---------------------------------------------------------------------------
# Each visitor gets a random id in a cookie. Documents are tagged with it, so
# two people using the site at the same time never see each other's files.
#
# The cookie is httponly, meaning page JavaScript can't read it - so a bug or
# a nasty script in the browser can't steal someone's session id.
COOKIE = "docmind_sid"


def get_session(request: Request) -> str:
    """The visitor's id, or a fresh one if they've never been here."""
    return request.cookies.get(COOKIE) or str(uuid.uuid4())


def set_session(response: Response, session: str) -> None:
    response.set_cookie(
        COOKIE, session,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,   # a week
    )


# ---------------------------------------------------------------------------
# RATE LIMITS
# ---------------------------------------------------------------------------
# Every question costs an API call. Without a limit, one visitor with a script
# could burn the whole free tier in a minute and the site stops working for
# everyone else.
#
# This is a simple in-memory counter: fine for one server, and honest about
# what it is. A real deployment behind several servers would need Redis.
ASK_LIMIT = int(os.getenv("ASK_LIMIT_PER_HOUR", "40"))
UPLOAD_LIMIT = int(os.getenv("UPLOAD_LIMIT_PER_HOUR", "15"))

_hits: dict[tuple[str, str], list[float]] = {}


def rate_limit(session: str, action: str, ceiling: int) -> None:
    """Allow `ceiling` of this action per hour, per visitor."""
    now = time.time()
    key = (session, action)

    # Drop anything older than an hour, then count what's left.
    recent = [t for t in _hits.get(key, []) if now - t < 3600]

    if len(recent) >= ceiling:
        wait = int((3600 - (now - recent[0])) / 60) + 1
        raise HTTPException(
            429,
            f"That's {ceiling} {action}s this hour — the limit. "
            f"Try again in about {wait} minutes.",
        )

    recent.append(now)
    _hits[key] = recent


# ---------------------------------------------------------------------------
# The shape of the /ask request body
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    # A LIST now, not one id - you can question several files at once.
    doc_ids: list[str]
    question: str
    # The browser sends the conversation back with each question. Keeping the
    # history on the client means the server stays stateless: no sessions to
    # expire, and two browser tabs can't tangle each other's conversations.
    history: list[dict] = []


# ---------------------------------------------------------------------------
# ROUTE 1: the page itself
# ---------------------------------------------------------------------------
@app.get("/")
def home():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# ROUTE 2: upload a file
# ---------------------------------------------------------------------------
@app.post("/upload")
async def upload(request: Request, response: Response, file: UploadFile = File(...)):
    session = get_session(request)
    set_session(response, session)
    rate_limit(session, "upload", UPLOAD_LIMIT)

    # One visitor can't fill the server with files on their own.
    if store.session_doc_count(session) >= store.MAX_DOCS_PER_SESSION:
        raise HTTPException(
            400,
            f"You can have {store.MAX_DOCS_PER_SESSION} files loaded at once. "
            f"Remove one to add another.",
        )

    file_bytes = await file.read()

    # Guard 1: size.
    if len(file_bytes) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(400, f"That file is over {MAX_FILE_MB}MB. Try a smaller one.")

    # SHORTCUT: have we processed this exact file before? Fingerprinting the
    # bytes is nearly instant, and a hit skips both reading and embedding -
    # a 1500-page PDF goes from minutes to under a second.
    fp = store.fingerprint(file_bytes)

    # Already uploaded by this same visitor? Reuse it rather than holding two
    # identical copies in memory.
    existing = store.find_by_fingerprint(fp, session)
    if existing:
        doc = store.DOCUMENTS[existing]
        return {
            "doc_id": existing,
            "filename": doc["filename"],
            "pages": len({c["page"] for c in doc["chunks"]}),
            "chunks": len(doc["chunks"]),
            "cached": True,
        }

    cached_id = store.load_cached(fp, file.filename, session)
    if cached_id:
        doc = store.DOCUMENTS[cached_id]
        pages = len({c["page"] for c in doc["chunks"]})
        print(f"[upload] {file.filename}: loaded from cache, no work needed")
        return {
            "doc_id": cached_id,
            "filename": file.filename,
            "pages": pages,
            "chunks": len(doc["chunks"]),
            "cached": True,
        }

    # Guard 2: type + readability. reader.py raises a clear message on failure.
    started = time.time()
    try:
        pages = reader.read_file(file.filename, file_bytes)
    except ValueError as error:
        raise HTTPException(400, str(error))
    except Exception:
        raise HTTPException(400, "That file couldn't be opened. It may be corrupted or password-protected.")

    read_time = time.time() - started

    # Guard 3: a scanned PDF has pages but no selectable text - say so plainly.
    if not pages:
        raise HTTPException(
            400,
            "No readable text found. This looks like a scanned document - "
            "it needs OCR before it can be searched.",
        )

    # Cut it up and embed it.
    chunks = chunker.chunk_pages(pages)
    embed_started = time.time()
    doc_id = store.add_document(file.filename, chunks, fp, session)
    store.evict_if_needed()
    embed_time = time.time() - embed_started

    # Print where the time actually went. On a slow upload this tells you
    # whether to blame page-reading or embedding, instead of guessing.
    print(
        f"[upload] {file.filename}: {len(pages)} pages, {len(chunks)} chunks | "
        f"read {read_time:.1f}s, embed {embed_time:.1f}s"
    )

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "cached": False,
    }


# ---------------------------------------------------------------------------
# ROUTE 3: ask a question
# ---------------------------------------------------------------------------
@app.post("/ask")
def ask(body: AskRequest, request: Request, response: Response):
    session = get_session(request)
    set_session(response, session)
    rate_limit(session, "question", ASK_LIMIT)

    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Type a question first.")

    if not body.doc_ids:
        raise HTTPException(400, "Select at least one document.")

    # SECURITY: only search documents this visitor actually uploaded.
    try:
        store.check_owned(body.doc_ids, session)
    except KeyError as error:
        raise HTTPException(404, str(error))
    store.touch(body.doc_ids)

    # 1. FOLLOW-UPS: "how is it trained?" means nothing to a search engine.
    #    Rewrite it into a standalone question first, using the conversation.
    #    Only happens when the question looks like a follow-up - see llm.py.
    try:
        search_question = llm.rewrite_followup(question, body.history)
    except Exception:
        search_question = question      # rewriting must never block an answer

    # 2. Find the most relevant parts ACROSS ALL selected documents.
    #    How many sections to pull depends on how much text there is: 5 is
    #    plenty for a 5-page handout and far too thin for a 1500-page syllabus.
    total_chunks = len(store.get_chunks(body.doc_ids))
    if total_chunks > 2000:
        top_k = 12
    elif total_chunks > 400:
        top_k = 8
    else:
        top_k = 5

    try:
        # multi_search splits multi-part questions and searches each part,
        # so "tell me about X and the syllabus for Y" finds both.
        chunks = store.multi_search(body.doc_ids, search_question, top_k=top_k)
    except KeyError as error:
        raise HTTPException(404, str(error))

    # 3. Let the LLM write the answer using ONLY those parts.
    full_text = store.get_full_text(body.doc_ids)
    try:
        result = llm.answer_question(
            question,
            chunks,
            full_text,
            body.history,
            all_chunks=store.get_chunks(body.doc_ids),
        )
    except Exception as error:
        # Show the REAL reason. A generic "couldn't reach the AI service" tells
        # you nothing - you can't tell a missing key from a typo'd model name.
        print(f"\n--- LLM call failed ---\n{type(error).__name__}: {error}\n")
        raise HTTPException(502, f"{type(error).__name__}: {error}")

    # 4. Send back the answer plus the raw evidence, so the UI can show both.
    result["evidence"] = [
        {
            "filename": c.get("filename", ""),
            "page": c["page"],
            "text": c["text"][:400],
            "score": round(c["score"], 3),
        }
        for c in chunks
    ]

    # Tell the UI if we rewrote the question, so it can show what was searched.
    if search_question != question:
        result["searched_as"] = search_question

    return result


# ---------------------------------------------------------------------------
# ROUTE 4: the text of one document (for the preview pane)
# ---------------------------------------------------------------------------
@app.get("/document/{doc_id}/text")
def document_text(doc_id: str, request: Request):
    session = get_session(request)
    if not store.owns(doc_id, session):
        raise HTTPException(404, "That document isn't available.")
    """
    Word files can't be shown in a browser the way PDFs can, so the preview
    pane falls back to displaying the extracted text. Grouped by page so the
    preview matches the page numbers used in citations.
    """
    doc = store.DOCUMENTS[doc_id]

    # Rebuild page-sized blocks from the chunks.
    pages: dict[int, list[str]] = {}
    for chunk in doc["chunks"]:
        pages.setdefault(chunk["page"], []).append(chunk["text"])

    return {
        "filename": doc["filename"],
        "pages": [
            {"page": number, "text": "\n".join(texts)}
            for number, texts in sorted(pages.items())
        ],
    }


# ---------------------------------------------------------------------------
# ROUTE 5: forget a document
# ---------------------------------------------------------------------------
@app.delete("/document/{doc_id}")
def remove(doc_id: str, request: Request):
    """Free the memory when the user removes a file from the list."""
    session = get_session(request)
    return {"removed": store.remove_document(doc_id, session)}
