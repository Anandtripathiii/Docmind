"""
probe_gemini.py
===============
Finds a model + API version combination that ACTUALLY works with your key.

Run it with:   python probe_gemini.py

WHY: your key can list a model but still get 404 when calling it, because
Google serves different API versions (v1 / v1beta) and the new "AQ." Auth keys
don't always route the same way as the old "AIza" ones.

Rather than guessing, this sends a tiny real request to each combination and
reports which ones come back OK. Copy the winner into your .env.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GEMINI_API_KEY", "").strip()
if not key:
    raise SystemExit("No GEMINI_API_KEY in .env")

# Versions Google currently serves.
VERSIONS = ["v1beta", "v1"]

# Models worth trying, cheapest/fastest first. All were in your account's list.
MODELS = [
    "gemini-flash-latest",       # alias - survives renames
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-2.0-flash",
]

print("testing combinations (this sends a 2-word prompt to each)...\n")

working = []

for version in VERSIONS:
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent"
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": "Say ok"}]}]},
                timeout=30,
            )
            code = response.status_code

            if code == 200:
                print(f"  WORKS   {version} / {model}")
                working.append((version, model))
            else:
                # Show the short reason, not the whole JSON blob.
                reason = response.json().get("error", {}).get("message", "")[:70]
                print(f"  {code}     {version} / {model}  -  {reason}")

        except Exception as error:
            print(f"  ERROR   {version} / {model}  -  {type(error).__name__}")

# ---- report ----
print()
if working:
    version, model = working[0]
    print("Put these two lines in your .env:\n")
    print(f"   GEMINI_MODEL={model}")
    print(f"   GEMINI_API_VERSION={version}")
    print("\nThen save and re-upload your document.")
else:
    print("Nothing worked. Your key authenticates but can't generate content.")
    print("\nSwitch to the offline option instead - no key, no account, no limits:")
    print("   1. install Ollama from https://ollama.com")
    print("   2. run:  ollama pull llama3.2")
    print("   3. in .env set:  LLM_PROVIDER=ollama")
