# DocMind

Ask questions about your PDFs and Word files. Every answer comes back with the
exact lines it was built from — and those lines are checked against your file
before you see them, so the AI can't invent a source.

![status](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Why this exists

Most document chatbots will confidently tell you something your document never
said. This one is built so that can't happen quietly:

1. The AI only ever sees text pulled from your file — never the whole internet,
   never its own memory.
2. It must copy the exact lines it used.
3. **Those lines are then searched for in the real document, in Python.** Any
   quote that isn't actually there gets deleted before it reaches the screen.
4. If nothing survives that check, the app says its confidence is low instead
   of pretending.
5. If your document doesn't cover the question, you get a clearly-labelled
   general-knowledge answer, not a fabricated document answer.

Step 3 is the part most RAG demos skip.

---

## Features

- **PDF and Word** (`.docx`) — text extraction with page numbers preserved
- **Multiple files at once** — search across them, tick files in or out
- **Follow-up questions** — "what is an LLM?" then "how is it trained?" works,
  because the question is rewritten into a standalone one before searching
- **Multi-part questions** — "what is X and what's the syllabus for Y" is split
  and searched separately, so one topic can't crowd out the other
- **Built-in PDF viewer** — click any citation to jump to that page
- **Hybrid search** — meaning (embeddings) + keywords, so it handles both
  "what's the fee?" and exact codes like "BS-103"
- **Caching** — re-uploading a processed file is instant
- **Three AI providers** — Gemini (free), Ollama (free, offline), Anthropic

---

## Quick start

```bash
git clone https://github.com/YOUR-USERNAME/docmind.git
cd docmind

pip install -r requirements.txt

cp .env.example .env      # then add your key (see below)
python -m uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>

The first run downloads a ~90MB embedding model. After that, search works
offline.

### Getting a key (free)

| Provider | Cost | What you need |
|---|---|---|
| **Gemini** | Free tier | A key from [aistudio.google.com](https://aistudio.google.com) — no credit card |
| **Ollama** | Free, offline | [ollama.com](https://ollama.com), then `ollama pull llama3.2`. No key at all |
| **Anthropic** | Paid | A key plus credits |

Set one line in `.env`:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

Something not working? Run the built-in checkers:

```bash
python check_setup.py     # tests your key and reports the exact problem
python list_models.py     # lists the models your key can actually use
python probe_gemini.py    # finds a working model + API version combination
```

---

## How it works

```
your file
   │
   ├─ reader.py    →  text, with page numbers kept
   ├─ chunker.py   →  small overlapping pieces
   └─ store.py     →  each piece becomes a vector (runs on your machine, free)

your question
   │
   ├─ llm.py       →  rewrite it if it's a follow-up
   ├─ store.py     →  find the best-matching pieces
   ├─ llm.py       →  write an answer using ONLY those pieces
   └─ llm.py       →  verify every quote against the real file
```

| File | Its one job |
|---|---|
| `app.py` | Web server and routes |
| `reader.py` | PDF/Word → plain text with page numbers |
| `chunker.py` | Text → small overlapping pieces |
| `store.py` | Embeddings, hybrid search, caching |
| `llm.py` | Talks to the AI provider, then **verifies every quote** |
| `static/index.html` | The entire UI — layout, styling, JavaScript |

---

## Tuning

| You want | Change |
|---|---|
| More context per answer | `top_k` in `app.py` |
| Bigger/smaller pieces | `CHUNK_SIZE` in `chunker.py` |
| Stricter "not in your document" | `RELEVANCE_FLOOR` in `llm.py` |
| Better search quality | `EMBED_MODEL=BAAI/bge-small-en-v1.5` in `.env` |
| Faster on big files | `EMBED_BATCH` in `.env` |
| Different answer style | `SYSTEM_PROMPT` in `llm.py` |
| Colours and motion | the `:root` block in `index.html` |

---

## Testing

```bash
python test_offline.py yourfile.pdf
```

Checks file reading, chunking, and the quote guard — no API key or internet
needed.

---

## Known limits

- **Scanned PDFs** have no selectable text and won't work. Would need OCR.
- **Memory only.** Uploaded documents are lost when the server restarts
  (processed vectors are cached to disk, so re-uploading is instant).
- **Documents live in RAM.** They're dropped when the server restarts, and the
  least-recently-used ones are evicted when memory fills. Processed vectors are
  cached to disk, so re-uploading is instant.
- **Old `.doc`** files aren't supported. Save as `.docx`.
- Page numbers follow the PDF's internal order, which can differ from printed
  page numbers if the document has front matter.

---

## Hosting it publicly

The app gives each visitor a session cookie, so people using it at the same
time can't see each other's documents. Rate limits and per-visitor file caps
are in `.env`.

A `Dockerfile` is included. **Hugging Face Spaces** is the easiest target — its
free CPU tier gives 16GB RAM and 2 cores, which is enough for the embedding
model. Create a Space, choose Docker, push this repo, and set `GEMINI_API_KEY`
as a Space secret (never commit it).

Two things to know before you do:

- **Everyone's questions use YOUR API key.** The rate limits exist to stop one
  visitor draining your free tier. Tune them in `.env`.
- **There's no login.** Anyone with the link can upload. Fine for a demo; add
  authentication before anything sensitive.

## Built with

FastAPI · sentence-transformers · pypdf · python-docx · NumPy

## License

MIT
