# DocMind — ask your PDF/Word file, get answers it can prove

Upload a PDF or `.docx`, ask questions, get an answer plus the **exact lines from
your file** that the answer was built on.

## Run it — free, no payment needed

The search half of this app (reading, chunking, embeddings) runs entirely on
your own machine and costs nothing, ever. Only the final answer needs a provider.

```bash
pip install -r requirements.txt
cp .env.example .env        # then pick a provider inside it
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

### Pick a provider — one line in `.env`

| | `LLM_PROVIDER=` | Cost | Needs |
|---|---|---|---|
| **Easiest free start** | `gemini` | Free tier | A key from aistudio.google.com — no credit card |
| **Totally free forever** | `ollama` | Free | ~5GB disk, 8GB RAM. No key, no internet |
| **Best quality** | `anthropic` | Paid | A key + credits |

**Gemini (recommended):** go to aistudio.google.com → "Get API key" → paste it
into `GEMINI_API_KEY` in your `.env`. Takes a minute. If you hit the daily cap,
switch `GEMINI_MODEL` to `gemini-2.5-flash-lite`, which has a bigger allowance.

**Ollama (no key at all):** install from ollama.com, run `ollama pull llama3.2`
once, then set `LLM_PROVIDER=ollama`. Now the whole app runs offline on your
computer. Slower, and answers are less polished, but free with no limits.

First run downloads a ~90MB embedding model. After that the search works offline.

## Which file does what

| File | Its one job |
|---|---|
| `app.py` | The web server. Two routes: `/upload` and `/ask`. |
| `reader.py` | File → plain text, keeping page numbers. |
| `chunker.py` | Text → small overlapping pieces. |
| `store.py` | The search engine (embeddings + keywords), in memory. |
| `llm.py` | Talks to your chosen provider, then **verifies every quote**. |
| `static/index.html` | The whole UI: styling, motion background, JS. |

## How it avoids making things up

1. **The AI only ever sees your text.** It gets the top 5 matching sections of
   your file and nothing else — not the whole internet, not its own memory.
2. **Temperature is 0.** No creative wandering.
3. **Quotes are checked in Python.** The AI must copy the lines it used. Before
   you see them, `llm.py` searches for each one in the real document. Quotes
   that aren't there get deleted — so a made-up source can't reach the screen.
4. **No verified quote → confidence drops to low.** The app admits it.
5. **Off-topic questions aren't forced.** If your file doesn't cover it, you get
   a pink "Not in your document" badge and a normal general-knowledge answer,
   clearly labelled as such.

## Knobs you'll probably want to turn

| Want | Change |
|---|---|
| Longer / shorter context per answer | `CHUNK_SIZE` in `chunker.py` |
| More sections used per answer | `top_k=5` in `app.py` |
| Stricter about "not in the document" | raise `RELEVANCE_FLOOR` in `llm.py` (0.30 → 0.40) |
| Better retrieval quality | swap `_MODEL_NAME` in `store.py` to `BAAI/bge-small-en-v1.5` |
| Different answer style | edit `SYSTEM_PROMPT` in `llm.py` |
| Switch AI provider | `LLM_PROVIDER` in `.env` — nothing else changes |
| Different colours / motion | the `:root` block at the top of `index.html` |

## Known limits (honest list)

- **Scanned PDFs** have no selectable text. You'd need OCR (`pytesseract`) added
  to `reader.py`.
- **Memory only.** Restart the server and uploaded files are gone. Swap
  `store.py` for Chroma or FAISS when you want it to persist.
- **Old `.doc`** files aren't supported — save as `.docx`.
- **Single user.** Fine locally; add sessions before putting it online.

## A note on free models

Smaller free models drift from the source text more often than paid ones. That
makes the quote verifier **more** important here, not less — it's what stops a
weaker model's guess from reaching your screen looking like a fact.

If answers feel vague on the free tier, check the "Verified lines" section under
each answer. If it's empty, the model was improvising and the app caught it.
