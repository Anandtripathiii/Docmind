"""
chunker.py
==========
JOB OF THIS FILE: cut the document into small pieces ("chunks").

WHY WE DO THIS:
We can't send a 200-page PDF to the AI every time - too big, too slow, and the
AI gets distracted. So we cut it into small pieces, and later we only send the
2-5 pieces that actually match the question.

Rules we follow:
- Cut on sentence ends, never in the middle of a word.
- Keep a little OVERLAP between pieces, so a sentence that sits on the border
  of two chunks isn't lost from both.
"""

import re

# Tune these two numbers if answers feel too narrow or too vague.
CHUNK_SIZE = 900       # characters per chunk (~150-180 words)
CHUNK_OVERLAP = 150    # characters repeated from the previous chunk


def split_into_sentences(text: str) -> list[str]:
    """
    Break text into sentences.

    We split after . ! ? or a newline. It's not perfect grammar-wise, but it's
    predictable and needs no extra library.
    """
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_pages(pages: list[dict]) -> list[dict]:
    """
    Turn [{"page": 1, "text": ...}] into a list of chunks:

        [{"id": 0, "page": 1, "text": "..."}, ...]

    Each chunk remembers its page number so we can cite it later.
    """
    chunks = []
    chunk_id = 0

    for page in pages:
        sentences = split_into_sentences(page["text"])

        current = ""          # the chunk we are currently filling up
        for sentence in sentences:

            # If adding this sentence would overflow the chunk, close the chunk.
            if len(current) + len(sentence) + 1 > CHUNK_SIZE and current:
                chunks.append({"id": chunk_id, "page": page["page"], "text": current.strip()})
                chunk_id += 1

                # Start the next chunk with the TAIL of this one (the overlap).
                current = current[-CHUNK_OVERLAP:] + " " + sentence
            else:
                current = (current + " " + sentence).strip()

        # Don't forget the leftover text at the end of the page.
        if current.strip():
            chunks.append({"id": chunk_id, "page": page["page"], "text": current.strip()})
            chunk_id += 1

    return chunks
