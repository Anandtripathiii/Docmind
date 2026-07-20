# DocMind

**[→ Open the app](https://docminddd.netlify.app)** · nothing to install

Ask questions about your PDFs and Word files. Every answer comes back with the
exact lines it was built from — and those lines are checked against your
document before you see them, so the AI can't invent a source.

---

## How to use it

1. Open **[docminddd.netlify.app](https://docminddd.netlify.app)**
2. Drop in a PDF or `.docx`
3. Ask a question

That's it. No account, no key, no setup.

**Your files never leave your browser.** They're read, cut up, and searched on
your own device. Only a few matching paragraphs are ever sent anywhere, and
nothing is stored on any server — close the tab and it's gone.

---

## What you get back

Every answer has four parts:

| | |
|---|---|
| **A badge** | green = from your document · amber = partly · pink = not in it |
| **The answer** | written using only text from your file |
| **In simple terms** | the same thing explained plainly |
| **Verified lines** | the exact sentences it used, with file and page |

Click any citation and the document opens at that page.

---

## Why it doesn't make things up

Most document chatbots will confidently tell you something your document never
said. This one is built so that can't happen quietly:

1. The AI only ever sees text pulled from your file — never the whole internet,
   never its own memory.
2. Temperature is 0, so it can't wander creatively.
3. It's required to copy the exact lines it used.
4. **Those lines are then searched for in your real text, in code.** Any quote
   that isn't found is deleted before it reaches the screen.
5. If nothing survives that check, the app lowers its confidence and says so.
6. If your document doesn't cover the question, you get a clearly-labelled
   general-knowledge answer instead of a fabricated document answer.

Step 4 is the part most similar projects skip. A model can claim anything, but
it can't fake a sentence that isn't in your file.

---

## What it can do

- **PDF and Word** (`.docx`), with page numbers preserved
- **Several files at once** — tick files in or out of the search
- **Follow-up questions** — ask "what is an LLM?" then "how is it trained?".
  The second question is rewritten into a standalone one before searching,
  because "how is it trained" alone matches nothing
- **Multi-part questions** — "what is X and what's the syllabus for Y" is split
  into two searches and merged fairly, so one topic can't crowd out the other
- **Hybrid search** — meaning *and* keywords together, so it handles both
  "what's the fee?" → "the charge is Rs 500" and exact codes like "BS-103"
- **Built-in reader** — the PDF sits beside the conversation
- **Works on phones** — where PDFs can't render inline, it shows the extracted
  text with page markers instead

---

## How it works

```
  YOUR BROWSER                          SERVERLESS FUNCTIONS
  ───────────────                       ────────────────────
  read the file      (pdf.js)
  cut into pieces
        │
        ├──── text ──────────────────►  /api/embed
        │                               turns it into vectors
        │◄─── vectors ───────────────
        │
  search the pieces
        │
        ├──── question + best few ───►  /api/ask
        │     matching pieces           asks Gemini
        │                               VERIFIES EVERY QUOTE
        │◄─── answer + proof ─────────
        │
  show it
```

The two functions exist for one reason: an API key must never be handed to a
browser. Everything else — reading, chunking, searching — runs on your device.

### The files

```
netlify/
├── public/index.html          the whole app: reading, chunking, search, UI
└── functions/
    ├── ask.mjs                calls Gemini, then verifies every quote
    └── embed.mjs              turns text into vectors for meaning-search
netlify.toml                   tells Netlify where those live
```

| File | What it does |
|---|---|
| `index.html` | Reads PDFs with pdf.js and Word with mammoth.js, splits text into ~900-character overlapping pieces, scores them against your question, draws everything |
| `ask.mjs` | Sends the question plus matching pieces to Gemini, then string-checks every returned quote against the real text and deletes any it can't find |
| `embed.mjs` | Converts text to vectors so search matches meaning, not just words. Tries several model names, since Google renames them |

---

## Run your own copy

Fork this repo, then on [netlify.com](https://netlify.com):

1. **Add new site → Import an existing project** → pick your fork
2. Leave the build settings alone — `netlify.toml` handles them
3. **Project configuration → Environment variables → Add a variable**
   - Key: `GEMINI_API_KEY`
   - Value: a free key from [aistudio.google.com](https://aistudio.google.com)
   - Tick **Contains secret values**
4. **Deploys → Trigger deploy → Deploy site**

Step 4 matters: environment variables are only read at build time, so a key
added to an already-built site does nothing until you redeploy.

Optional overrides, if a model name stops working:

| Variable | Default |
|---|---|
| `GEMINI_MODEL` | `gemini-flash-lite-latest` |
| `EMBED_MODEL` | tries `gemini-embedding-001`, then `text-embedding-004` |

**Note:** every visitor's questions spend *your* API key, and there's no login.
Fine for a demo — watch your usage.

---

## Known limits

- **Scanned PDFs** are images, not text, so there's nothing to read. They'd
  need OCR.
- **Very large files** (over ~600 sections) drop to keyword-only search. Getting
  vectors for thousands of pieces would mean dozens of slow API calls.
- **Refreshing clears your files**, since nothing is stored on a server.
- **Old `.doc`** files aren't supported — save as `.docx`.
- Page numbers follow the PDF's internal order, which can differ from printed
  page numbers when a document has front matter.
- Answers must finish inside the serverless time limit, so very long questions
  across many files can time out. Untick a file or ask something narrower.

---

## Built with

pdf.js · mammoth.js · Netlify Functions · Google Gemini

The repo root also holds an earlier version of this project built as a Python
server. It isn't needed for the live site.

## License

MIT
