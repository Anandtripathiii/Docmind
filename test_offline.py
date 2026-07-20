"""
test_offline.py
===============
Checks the parts that don't need an API key or internet:
reading files, chunking, and the quote-verification guard.

Run it with:   python test_offline.py sample.pdf

If you don't have a file handy, any PDF or .docx will do.
"""

import sys

import chunker
import reader

# llm.py imports the anthropic client at the top, which needs a key. We only
# want the two pure-Python checker functions, so we stub the import out.
import types
if "anthropic" not in sys.modules:
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kwargs: None
    sys.modules["anthropic"] = fake
import llm


def main(path: str):
    # ---- CHECK 1: can we read the file? ----
    pages = reader.read_file(path, open(path, "rb").read())
    chunks = chunker.chunk_pages(pages)
    print(f"read {len(pages)} pages -> {len(chunks)} chunks")
    for c in chunks[:3]:
        print(f"  page {c['page']}: {c['text'][:70]}...")

    # ---- CHECK 2: does the quote guard catch made-up quotes? ----
    full_text = "\n".join(c["text"] for c in chunks)

    # Take a real sentence from the file, and invent one that isn't in it.
    real_line = chunks[0]["text"][:80]
    fake_line = "This document guarantees a full refund under all circumstances."

    kept = llm._verify_quotes([real_line, fake_line], full_text)

    print("\nquote check:")
    print(f"  real line kept? {real_line in kept}   (should be True)")
    print(f"  fake line kept? {fake_line in kept}   (should be False)")

    if real_line in kept and fake_line not in kept:
        print("\nPASS - the guard keeps real quotes and deletes invented ones.")
    else:
        print("\nFAIL - check _verify_quotes in llm.py")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python test_offline.py <your-file.pdf or .docx>")
    else:
        main(sys.argv[1])
