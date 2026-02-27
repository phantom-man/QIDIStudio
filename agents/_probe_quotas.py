"""
Probe each Gemini model with a 1-token call.
Reports: OK, RATE_LIMITED (with limit from error), NOT_AVAILABLE, or ERROR.
Also uses the REST /v1beta/models endpoint to list available models.
"""
import os, re, sys, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / ".env")

PROJECT  = os.environ.get("GOOGLE_CLOUD_PROJECT",  "crafty-hook-483415-b3")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
print(f"Auth: Vertex AI ADC  project={PROJECT}  location={LOCATION}")

# ── 1. List models via Vertex AI SDK ──────────────────────────────────────────
try:
    from google import genai
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    text_models = [
        m.name.replace("models/", "")
        for m in client.models.list()
        if hasattr(m, "supported_actions") and "generateContent" in (m.supported_actions or [])
        or "gemini" in m.name
    ]
    print(f"\n=== Available models via Vertex ({len(text_models)}) ===")
    for m in sorted(text_models)[:20]:
        print(f"  {m}")
except Exception as e:
    print(f"[model list error] {e}")

# ── 2. Probe candidates ───────────────────────────────────────────────────────
candidates = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

print(f"\n=== Live probe (1-token call per model) ===")
for model in candidates:
    try:
        llm = ChatGoogleGenerativeAI(model=model, temperature=0.0,
                                     project=PROJECT, location=LOCATION)
        resp = llm.invoke([HumanMessage(content="Say OK")])
        print(f"  OK            {model}")
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            m = re.search(r"limit: (\d+)", msg)
            m2 = re.search(r"Quota exceeded for metric: ([^\,]+)", msg)
            lim = m.group(1) if m else "?"
            metric = m2.group(1).split("/")[-1] if m2 else "?"
            print(f"  RATE_LIMITED  {model:35s}  free_limit={lim}  ({metric})")
        elif "404" in msg or "not found" in msg.lower() or "deprecated" in msg.lower():
            print(f"  NOT_AVAILABLE {model}")
        else:
            short = msg.replace("\n", " ")[:100]
            print(f"  ERROR         {model:35s}  {short}")
    sys.stdout.flush()

print("\nDone.")
