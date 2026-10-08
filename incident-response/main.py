# incident-response/main.py
# Run from incident-response/:  uv run uvicorn main:app --host 0.0.0.0 --port 8001
# (0.0.0.0 is required so the Grafana container can reach it via host.docker.internal)
import datetime
import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request

app = FastAPI()

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EVIDENCE = HERE / "incident-evidence"
EVIDENCE.mkdir(exist_ok=True)

LOKI = "http://localhost:3100"
TEMPO = "http://localhost:3200"
_busy = threading.Lock()  # one agent run at a time (Grafana re-sends alerts)


def fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:  # evidence collection must never crash the responder
        return {"error": str(e), "url": url}


def collect_evidence(stamp: str, payload: dict) -> Path:
    """Save alert + recent logs + error traces so the agent (and humans) can investigate."""
    now = time.time_ns()
    start = now - 15 * 60 * 10**9
    logs = fetch(f"{LOKI}/loki/api/v1/query_range?" + urllib.parse.urlencode({
        "query": '{service_name="order-tracker"}', "start": start, "end": now,
        "limit": 200, "direction": "backward"}))
    found = fetch(f"{TEMPO}/api/search?" + urllib.parse.urlencode({
        "q": "{ status = error }", "limit": 5,
        "start": int(start / 1e9), "end": int(now / 1e9)}))
    traces = [fetch(f"{TEMPO}/api/traces/{t['traceID']}") for t in found.get("traces", [])[:3]]
    path = EVIDENCE / f"evidence-{stamp}.json"
    path.write_text(json.dumps({"alert": payload, "logs": logs, "trace_search": found,
                                "traces": traces}, indent=2))
    return path


TEST_PROMPT = (
    "You are the on-call responder for the Order Tracker app. This is a TEST alert. "
    "Do not change any files. Reply with a short JSON diagnosis with keys: "
    "diagnosis, action, confidence. Alert: {alert}")

INCIDENT_PROMPT = (
    "You are the on-call responder for the Order Tracker app (repo root is the current directory). "
    "Grafana fired a 5xx alert. Evidence (alert, Loki logs, Tempo traces) is in: {evidence}\n"
    "1. Read the evidence and find the root cause in the code.\n"
    "2. Apply the smallest possible fix; touch only the file(s) that contain the bug.\n"
    "3. Run `uv run pytest -q`.\n"
    "4. Rebuild: `docker compose up --build -d --wait`.\n"
    "5. Verify `curl -i http://localhost:8000/api/orders/express-1002` no longer returns 5xx.\n"
    "6. If you cannot fix or verify it, change nothing further and say ESCALATE.\n"
    "Finish with a JSON object: root_cause, files_changed, verification, status (fixed|escalate).")


def run_agent(prompt: str, stamp: str) -> str:
    try:
        r = subprocess.run(["opencode", "run", prompt], cwd=REPO,
                           capture_output=True, text=True, timeout=1200)
        out = (r.stdout or "").strip() or f"(no stdout, rc={r.returncode}) {r.stderr[-500:]}"
    except Exception as e:
        out = f"agent failed to run: {e}"
    (EVIDENCE / f"response-{stamp}.txt").write_text(out)
    return out


def handle_real(stamp: str, payload: dict) -> None:
    try:
        evidence = collect_evidence(stamp, payload)
        run_agent(INCIDENT_PROMPT.format(evidence=evidence), stamp)
    finally:
        _busy.release()


@app.post("/alerts")
async def alerts(request: Request):
    payload = await request.json()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (EVIDENCE / f"alert-{stamp}.json").write_text(json.dumps(payload, indent=2))

    firing = [a for a in payload.get("alerts", []) if a.get("status") == "firing"]
    if not firing:
        return {"saved": f"alert-{stamp}.json", "action": "ignored (no firing alerts)"}

    is_test = any(a.get("labels", {}).get("test") == "true" for a in firing)
    if not _busy.acquire(blocking=False):
        return {"saved": f"alert-{stamp}.json", "action": "agent already running"}

    if is_test:  # synchronous: the Q5 curl prints the agent's answer
        try:
            out = run_agent(TEST_PROMPT.format(alert=json.dumps(payload)), stamp)
        finally:
            _busy.release()
        return {"saved": f"alert-{stamp}.json", "agent": out}

    # real incident: Grafana's webhook would time out, so run in the background
    threading.Thread(target=handle_real, args=(stamp, payload), daemon=True).start()
    return {"saved": f"alert-{stamp}.json", "action": "agent started"}
