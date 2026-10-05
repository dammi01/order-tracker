# incident-response/main.py
import json, subprocess, datetime
from pathlib import Path
from fastapi import FastAPI, Request

app = FastAPI()
EVIDENCE = Path("incident-evidence")
EVIDENCE.mkdir(exist_ok=True)

@app.post("/alerts")
async def alerts(request: Request):
    payload = await request.json()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = EVIDENCE / f"alert-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2))
    result = subprocess.run(
        ["opencode", "run",
         "You are an on-call responder for the Order Tracker app. Investigate this alert read-only and reply with a short JSON diagnosis with keys: diagnosis, action, confidence. Alert: "
         + json.dumps(payload)],
        capture_output=True, text=True, timeout=600)
    agent_out = (result.stdout or "").strip()
    out = EVIDENCE / f"response-{stamp}.txt"
    out.write_text(result.stdout)
    return {"saved": str(path), "agent": result.stdout[-500:]}
