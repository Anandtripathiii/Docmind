"""
check_setup.py
==============
Tests your .env settings WITHOUT running the whole app.

Run it with:   python check_setup.py

It tells you exactly which piece is broken - missing key, wrong model name,
no internet - instead of a vague "couldn't reach the AI service".
"""

import os

from dotenv import load_dotenv

# ---- 1. Is there even a .env file? ----
if not os.path.exists(".env"):
    print("PROBLEM: no .env file in this folder.")
    print("   Fix: rename '.env.example' to exactly '.env'")
    print("   (Windows may hide the extension - turn on 'File name extensions' in Explorer)")
    raise SystemExit(1)

load_dotenv()
print("found .env\n")

# ---- 2. Which provider did you pick? ----
provider = os.getenv("LLM_PROVIDER", "").lower().strip()
print(f"LLM_PROVIDER = {provider!r}")

if provider not in ("gemini", "ollama", "anthropic"):
    print("PROBLEM: LLM_PROVIDER must be exactly gemini, ollama, or anthropic.")
    raise SystemExit(1)

# ---- 3. Is the key present and does it look right? ----
if provider == "gemini":
    key = os.getenv("GEMINI_API_KEY", "").strip()

    # Show what Python ACTUALLY read, masked. A vague "key is missing" hides
    # the difference between an unsaved file, a placeholder, and a wrong key.
    if key:
        shown = key[:6] + "..." + key[-4:] if len(key) > 12 else key
        print(f"GEMINI_API_KEY   = {shown}  ({len(key)} characters)")
    else:
        print("GEMINI_API_KEY   = (nothing)")

    if not key:
        print("\nPROBLEM: the key is empty on disk.")
        print("   Most likely: you typed it in your editor but didn't SAVE (Ctrl+S).")
        raise SystemExit(1)

    if key.startswith("paste"):
        print("\nPROBLEM: still the placeholder text 'paste-your-key-here'.")
        print("   Either you edited a different file, or the edit wasn't saved.")
        raise SystemExit(1)

    if " " in key:
        print("\nPROBLEM: there's a space inside the key. Remove it.")
        raise SystemExit(1)

    # KEY FORMATS (as of mid-2026):
    #   AQ.Ab...  "Auth key"     - the CURRENT format. AI Studio issues these now.
    #   AIza...   "Standard key" - the OLD format, being phased out by Google.
    # Both are real Gemini keys. Don't reject either one.
    if key.startswith("ya29."):
        print("\nPROBLEM: 'ya29.' is a short-lived OAuth access token, not an API key.")
        print("   Fix: https://aistudio.google.com  ->  Get API key  ->  Create API key")
        raise SystemExit(1)

    if key.startswith("AQ."):
        print("   (new-style Auth key - this is the current format, good)")
    elif key.startswith("AIza"):
        print("   (old-style Standard key - still works for now, but Google is")
        print("    retiring these. Create a fresh key if it starts failing.)")

# ---- 4. Actually call the provider ----
print("\ncalling the provider...")

import llm  # imported here so the .env values above are already loaded

try:
    reply = llm._PROVIDERS[provider](
        "Reply with only this JSON: {\"ok\": true}",
        "Say ok.",
    )
    print("SUCCESS - the provider replied:")
    print(f"   {reply.strip()[:120]}")
    print("\nYour setup works. Start the app with: python -m uvicorn app:app --reload")

except Exception as error:
    print(f"FAILED: {type(error).__name__}: {error}\n")
    print("Common causes:")
    print("  401 / 403        -> key wrong, revoked, or restricted to the wrong API.")
    print("                      For AQ. keys: in AI Studio open your key and make")
    print("                      sure it's allowed to call the Gemini API.")
    print("  404              -> the model name in .env doesn't exist")
    print("  429              -> free tier limit hit, wait a minute")
    print("  ConnectionError  -> no internet, or a firewall is blocking it")
    print("\nIf nothing here fits, switch to the offline option - no key needed:")
    print("  1. install Ollama from https://ollama.com")
    print("  2. run:  ollama pull llama3.2")
    print("  3. set LLM_PROVIDER=ollama in .env")
