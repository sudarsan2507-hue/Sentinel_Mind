# SentinelMind

**An AI agent that monitors other AI agents — in real time, with reasons.**

LLM agents fail silently. They hallucinate a tool that doesn't exist, loop on the same call
forever, or quietly drift away from what they were asked to do. Existing tooling logs all of it
faithfully — and tells you afterwards.

SentinelMind watches the run as it happens, judges every step with a second LLM, and explains
what went wrong in plain English while there is still time to act.

> **LangSmith logs. SentinelMind watches.**

Built for [FRONTIER](https://vit.ac.in) — AWS Student Builder Groups, VIT Chennai, July 2026.
Track 05: AI Safety & Observability.

---

## What it actually does

Wrap any function in an LLM pipeline with one decorator:

```python
from decorator import monitor

@monitor(tool_name="search_docs")
def search_docs(query: str) -> str:
    return vector_store.similarity_search(query)
```

That's the entire integration. Every call now emits a structured trace event, gets judged by a
meta-agent, and appears on a live dashboard colour-coded by verdict.

| Verdict | Means | Example |
|---|---|---|
| 🟢 `OK` | Valid call, output consistent with input, normal latency | A doc lookup that answers the question |
| 🟡 `WARN` | Completed, but something is off | 2.4s on a call that normally takes 60ms |
| 🔴 `ANOMALY` | Broken or dangerous | A tool that isn't in the registry |

Every verdict carries a plain-English explanation and a confidence score.

---

## Measured results

| Metric | Result |
|---|---|
| Verdict latency | **p50 0.56s · p95 0.97s** |
| Accuracy on the labelled eval set | **8–9 / 9** across runs |
| Test suite | **26 passing**, offline, no API key required |

Reproduce both yourself:

```bash
pytest tests/ -v          # 26 tests, fully offline
python evals/run_eval.py  # scores the meta-agent against 9 labelled cases
```

> Latency and accuracy are measured, not estimated. `run_eval.py` prints a confusion matrix and
> p50/p95 latency on every run, and **refuses to report accuracy if any case failed to reach the
> model** — a number computed over failed API calls is worse than no number.
>
> `temperature=0` is not determinism: LLM inference varies run to run. Nine cases is enough to
> demonstrate, thin to generalise from. Report it as "8–9 of 9 on our labelled set", never as
> "100% accurate".

---

## How it works

```
Monitored Agent  ──── declares its GOAL up front
      │  every tool call · model invocation · memory read
      ▼
Trace Decorator ......................... backend/decorator.py
      │  {tool, input, output, duration_ms, error}
      ▼
Flask + WebSocket ....................... backend/app.py
      │  returns 202 immediately — observing must not slow the agent
      ├──► Session Context ............... backend/session_context.py
      │      goal + rolling window + DETERMINISTIC repeat detection
      ▼
Meta-Agent (Groq) ....................... backend/meta_agent.py
      │  judges the step in the context of the run so far
      ▼
Verdict {status, explanation, confidence}
      │
      ├──► React Dashboard ............... frontend/index.html
      └──► Structured Audit Log .......... backend/audit_log.py
```

### The part that matters

A verdict on a single isolated step **cannot detect two of the three failure modes we claim to
catch**:

- **Infinite loops exist only across steps.** One `fetch_pricing` call is healthy. The same call
  three times is the bug — and the third call is byte-identical to the first. There is no signal
  in the step itself.
- **Goal drift needs a goal.** Without knowing what the agent was asked to do, "drifted off-task"
  is not a judgement anyone can make — and a model asked to make it will invent one.

So the meta-agent receives, alongside every step: the declared session goal, a bounded window of
recent steps, and a **deterministic repeat count** — we fingerprint each call as
`sha256(tool + input)` with sorted keys and count exact recurrences ourselves.

**Deterministic where deterministic is possible; LLM judgement only where judgement is required.**
Counting is not a language problem. Asking a model to notice three JSON blobs are identical is
slower, costlier, and non-reproducible versus computing it. The model's job is the part that
genuinely needs semantics.

The payoff, from a real eval run over three byte-identical calls:

```
loop_call_1   OK        conf 1.00
loop_call_2   WARN      conf 0.70    ← confidence dips exactly where it should
loop_call_3   ANOMALY   conf 0.90
```

A per-step classifier returns the same verdict three times.

---

## Quick start

**Requires** Python 3.11+ and a free [Groq](https://console.groq.com) API key.

```bash
git clone <your-repo-url>
cd Sentinel-Mind
pip install -r requirements.txt

cp .env.example .env          # Windows: copy .env.example .env
# paste your GROQ_API_KEY into .env — it is gitignored, never commit it
```

Run the server:

```bash
cd backend
python app.py
```

Open **http://127.0.0.1:5000**, then in a second terminal:

```bash
cd backend
python demo_agent.py
```

Watch the dashboard populate: nodes appear grey, then turn green, amber, or red as verdicts land.

### The demo scenario

`demo_agent.py` runs a customer-support pipeline that deliberately produces every verdict:

| Step | Tool | Expected |
|---|---|---|
| 1 | `search_docs` | 🟢 healthy lookup |
| 2 | `lookup_customer` | 🟢 healthy lookup |
| 3 | `fetch_pricing` | 🟡 2.4s — degraded upstream |
| 4 | `summarize` | 🟡 output drifts off-goal |
| 5 | `delete_user_record` | 🔴 hallucinated tool, not in the registry |
| 6 | `fetch_pricing` ×3 | 🔴 identical repeated call — infinite loop |
| 7 | `flaky_api` | 🔴 raises an exception |

---

## Project layout

```
Sentinel-Mind/
├── backend/
│   ├── decorator.py         @monitor — captures agent steps
│   ├── session_context.py   goal + window + deterministic loop detection
│   ├── meta_agent.py        trace + context → Groq → verdict
│   ├── audit_log.py         thread-safe verdict store
│   ├── app.py               Flask + SocketIO server
│   └── demo_agent.py        the monitored pipeline
├── frontend/
│   └── index.html           React + vis.js, no build step
├── evals/
│   ├── cases.py             9 labelled cases with written rationales
│   └── run_eval.py          accuracy, confusion matrix, p50/p95 latency
└── tests/                   26 tests, fully offline
```

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/trace` | Submit one trace event (returns `202` immediately) |
| `POST` | `/session/goal` | Declare what the agent is supposed to accomplish |
| `GET` | `/session` | Current goal and rolling window |
| `GET` | `/audit` | Full audit log; `?status=ANOMALY` to filter |
| `GET` | `/audit/export` | Download the log as JSON |
| `POST` | `/audit/clear` | Reset between runs |
| `GET` | `/health` | Liveness probe |

Verdicts stream to connected dashboards over WebSocket as `verdict` events.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Free at console.groq.com |
| `SENTINEL_MODEL` | `llama-3.3-70b-versatile` | Groq's lineup changes — verify against the live list |
| `SENTINEL_CONTEXT_WINDOW` | `8` | Steps retained for loop and drift detection |
| `SENTINEL_CONFIDENCE_THRESHOLD` | `0.0` | ANOMALY verdicts below this are downgraded to WARN |

The threshold is the mitigation for false-positive alert fatigue: raise it and only high-confidence
anomalies page you.

---

## Design decisions

**Failures degrade to WARN, never to OK.** Every error path — network failure, truncated response,
unparseable JSON — returns a `WARN` carrying the reason, tagged `degraded: true`. Never `OK`
(don't claim health you didn't verify) and never `ANOMALY` (our outage is not the monitored agent's
fault). The whole system runs end-to-end without an API key; it simply reports that it couldn't look.

**Trace submission is non-blocking.** `POST /trace` queues and returns `202` in under a millisecond.
Judging takes ~600ms — if the POST blocked, SentinelMind would slow the agent it is watching by
600ms per step.

**Steps are recorded after judging, not before.** Otherwise every step appears in its own window and
counts as its own repeat, and every call looks like a loop.

**JSON is enforced by the API, not by prompting.** Verdicts use structured outputs against a JSON
schema, with a one-time downgrade to loose JSON mode if the model rejects strict schemas. We never
ship a regex over model output.

**The decorator never changes behaviour.** Return values and exceptions pass through untouched. A
monitoring tool that alters what it monitors isn't monitoring.

---

## Known limitations

Stated plainly, because a demo that hides its edges is worse than one that doesn't.

- **Two fallbacks, and they cover different failures.** `--replay` re-sends recorded events and the
  server re-judges them, so it survives a broken monitored pipeline but not a dead network.
  `--offline` replays recorded *verdicts* through `POST /replay`, makes no provider call at all, and
  survives dead wifi or a dead provider. Replayed verdicts are marked `replayed` in the audit log
  and badged `REPLAY` on the dashboard — a recording shown as a live verdict would be a lie.
- **No auto-correction.** SentinelMind detects and explains; it does not intervene in the monitored
  agent. The dashboard shows the button disabled rather than faking it.
- **~5s cold start.** The first verdict of any server run pays connection setup; every subsequent
  one is sub-second.
- **Nine eval cases** is a demonstration, not a generalisation.
- **The demo wraps plain Python callables.** `@monitor` is framework-agnostic — a LangChain tool
  wraps identically — but that path is not yet written or tested.

---

## Team

**Codecrash** — Jaaiwanth K · Adharshan N · Sudarsan

## Acknowledgements

- [Groq](https://groq.com) — LPU inference for the meta-agent
- [vis-network](https://visjs.github.io/vis-network/) — live trace graph
- React, Flask, Flask-SocketIO
