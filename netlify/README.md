# DocMind — Netlify edition

Ask questions about your PDFs and Word files. Every answer comes with the exact
lines it was built from, and those lines are checked against your document
before you see them — so the AI can't invent a source.

**Your files never leave your browser.** They're read, cut up, and searched on
your own machine. Only a few matching text sections are ever sent anywhere.

---

## Deploy it (about 5 minutes)

1. Push this folder to GitHub.
2. On [netlify.com](https://netlify.com): **Add new site → Import an existing project** → pick the repo.
3. Leave the build settings alone — `netlify.toml` already sets them.
4. **Site configuration → Environment variables → Add:**

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key from [aistudio.google.com](https://aistudio.google.com) |

5. Deploy. Done — anyone with the link can use it, no installation.

Optional variables if a model name stops working:

| Key | Default |
|---|---|
| `GEMINI_MODEL` | `gemini-flash-latest` |
| `EMBED_MODEL` | `gemini-embedding-001` |
| `GEMINI_API_VERSION` | `v1beta` |

**Never put the key in a file.** It belongs in Netlify's environment
variables, which is why `.gitignore` blocks `.env`.

---

## Why it's built this way

Netlify Functions run JavaScript, TypeScript, and Go — **not Python**. So the
original FastAPI + PyTorch version can't run here at all. Instead:

| Job | Where it happens |
|---|---|
| Read the PDF/Word file | Your browser (pdf.js, mammoth.js) |
| Cut it into sections | Your browser |
| Search those sections | Your browser |
| Turn text into vectors | `/api/embed` — needs the secret key |
| Write the answer | `/api/ask` — needs the secret key |
| **Verify every quote** | `/api/ask`, before anything reaches you |

The two functions exist only because an API key must never be handed to a
browser. Everything else stays local.

---

## How it avoids making things up

1. The AI only sees text pulled from your file.
2. Temperature is 0 — no creative wandering.
3. It must copy the exact lines it used.
4. **Those lines are searched for in your real text, in JavaScript.** Quotes
   that aren't found are deleted before rendering.
5. No verified quote left? Confidence drops to low and the app says so.
6. Question not covered by your file? You get a clearly-labelled
   general-knowledge answer, not a fabricated document answer.

Step 4 is the part most RAG demos skip.

---

## Features

- PDF and Word (`.docx`), page numbers preserved
- Multiple files at once — tick files in or out of the search
- Multi-part questions split and searched separately, so one topic can't
  crowd out the other
- Hybrid search: meaning (vectors) + keywords, with stemming so "dog" matches "dogs"
- Built-in PDF viewer; click any citation to jump to that page
- Follow-up questions use recent conversation for context

---

## Files

```
public/index.html          the entire app - reading, chunking, searching, UI
netlify/functions/ask.mjs  calls Gemini, then verifies every quote
netlify/functions/embed.mjs turns text into vectors
netlify.toml               tells Netlify where things live
```

## Known limits

- **Scanned PDFs** have no selectable text and won't work — they'd need OCR.
- **Very large files** (over 600 sections) skip vector search and use keywords
  only, to avoid dozens of slow API calls. Answers still work.
- **Refreshing the page clears your files** — nothing is stored on a server.
- **Visitors spend YOUR API key.** There's no login. Fine for a demo; watch
  your usage, and add auth before anything sensitive.
- Free-tier functions have a request timeout, so extremely long documents may
  need splitting.

## License

MIT
