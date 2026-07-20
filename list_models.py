"""
list_models.py
==============
Asks Google which models YOUR key is allowed to use.

Run it with:   python list_models.py

WHY THIS EXISTS:
A 404 from the API means the model name in your .env doesn't exist for your
account. Model names change over time - guessing wastes time. This asks.

Copy whichever name it prints into GEMINI_MODEL in your .env file.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("GEMINI_API_KEY", "").strip()
if not key:
    raise SystemExit("No GEMINI_API_KEY found in .env")

print("asking Google which models your key can use...\n")

response = requests.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    headers={"x-goog-api-key": key},
    timeout=30,
)

if response.status_code != 200:
    print(f"FAILED ({response.status_code}): {response.text[:300]}")
    raise SystemExit(1)

models = response.json().get("models", [])

# We only care about models that can answer prompts. Many entries in the list
# are embedding-only or image models, which would 404 the same way.
usable = []
for model in models:
    methods = model.get("supportedGenerationMethods", [])
    if "generateContent" in methods:
        # Names come back as "models/gemini-x-y" - strip the prefix, .env wants
        # just the short name.
        usable.append(model["name"].replace("models/", ""))

if not usable:
    print("Your key works, but no text models are available to it.")
    raise SystemExit(1)

print(f"{len(usable)} usable models found:\n")
for name in usable:
    print(f"   {name}")

# Suggest a good default: prefer a "flash" model, they're the fast cheap ones
# and the ones with the biggest free-tier allowance.
flash = [n for n in usable if "flash" in n and "lite" not in n and "preview" not in n]
lite = [n for n in usable if "lite" in n]

pick = (flash or lite or usable)[0]

print(f"\nPut this in your .env file:\n")
print(f"   GEMINI_MODEL={pick}\n")
if lite:
    print(f"If you hit daily limits, {lite[0]} usually has a bigger allowance.")
