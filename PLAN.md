# SentinelMind — Plan

**Team:** Codecrash · **Event:** FRONTIER (AWS Student Builder Groups) · **Dates:** July 30–31, 2026
**Track:** 05 — AI Safety & Observability
**One-liner:** *"LangSmith logs. SentinelMind intervenes."*

---

## 1. What it is

A real-time AI agent that monitors other AI agents. It wraps any LLM pipeline with a thin Python
decorator, captures every step, streams the trace to a meta-agent (Claude), gets a verdict
(`OK` / `WARN` / `ANOMALY`) plus a plain-English explanation, and renders it live on a dashboard.

**Target:** anomaly flagged in **under 3 seconds**, vs. 10+ minutes with log-based debugging.

---

## 2. Architecture

```
Monitored Agent  (demo pipeline)  --- declares its GOAL up front
      |  every tool call / model invocation / memory read
      v
Trace Decorator  (backend/decorator.py)   <- thin Python wrapper, zero config
      |  structured JSON event: {tool, input, output, timestamp, duration_ms, error}
      v
Event Bus -> Flask-SocketIO WebSocket
      |
      +--> Session Context (backend/session_context.py)
      |      goal + sliding window of recent steps
      |      + DETERMINISTIC repeat count (loop detection)
      v
Meta-Agent  (backend/meta_agent.py)  ->  Groq
      |  judges the step IN CONTEXT of the run so far
      v
Verdict: {status, explanation, confidence}
      |                      |
      v                      v
React Dashboard          Audit Log
(live vis.js node graph)  (structured JSON, backend/audit_log.py)
```

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.14 + Flask | Local runtime confirmed: Python 3.14.2 |
| Real-time | Flask-SocketIO + WebSocket | Server pushes verdicts to dashboard |
| Monitored agent | Plain Python callables (LangChain pending) | Demo pipeline only — the thing being watched |
| Meta-agent LLM | **Groq**, `llama-3.3-70b-versatile` | See §4 — provider changed from the deck |
| Frontend | React via CDN, no build step | Judges can open `index.html` directly |
| Graph | vis.js | Live node graph, colored by verdict |
| Tests | pytest | 15 tests, see §7 |

---

## 4. Provider decision (deviation from the deck)

**The deck says Claude Sonnet. We are running on Groq.** Reasons: free tier, and LPU inference is
fast, which directly serves the sub-3-second claim — a verdict is a short classification, not a
reasoning problem, so raw throughput matters more than frontier reasoning here.

> ⚠️ **The deck must be updated.** Slide 4 ("Meta-Agent: Claude Sonnet") and reference [1]
> ("Anthropic. Claude API Documentation … Model: claude-sonnet-4-6") are both now wrong. Slide 7
> needs a Groq reference instead. This is a blocking pre-submission task.

Groq serves open models behind an **OpenAI-compatible** endpoint, so the client is `openai` pointed
at `https://api.groq.com/openai/v1`. Model is `llama-3.3-70b-versatile`, overridable with
`SENTINEL_MODEL` — verify against the live list at console.groq.com, since Groq's lineup moves.

Two things that shape `meta_agent.py`:

1. **`temperature=0`.** Unlike Sonnet 5 (which rejects sampling params), Groq accepts them. A verdict
   should not vary between runs on the same input.
2. **Structured output support varies by model.** We request strict `json_schema` first; if the model
   rejects it, we downgrade once to `json_object`, cache that decision on the instance, and never pay
   the retry again. A model swap therefore can't break the demo mid-run.

   The downgrade fires **only on a 400 that names the format** — not on 401, 429, timeouts, or
   dropped connections. It is permanent for the life of the process, so downgrading for the wrong
   reason silently costs us strict schema enforcement for the rest of the run, with nothing to show
   for it: `json_object` works fine, so the weaker guarantee is invisible. `GET /health` reports the
   resolved mode (`untested` / `json_schema` / `json_object`) so you know what you are demoing
   instead of inferring it.

Call shape:

```python
client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    max_tokens=512,
    temperature=0,                    # verdicts should be reproducible
    response_format=STRICT_FORMAT,    # falls back to {"type": "json_object"}
    messages=[
        {"role": "system", "content": HEALTHY_REASONING_PROMPT},
        {"role": "user", "content": trace_json},
    ],
)
```

`VERDICT_SCHEMA`:

```json
{
  "type": "object",
  "properties": {
    "status":      {"type": "string", "enum": ["OK", "WARN", "ANOMALY"]},
    "explanation": {"type": "string"},
    "confidence":  {"type": "number"}
  },
  "required": ["status", "explanation", "confidence"],
  "additionalProperties": false
}
```

**Failure handling:** every failure path — transport error, empty response, `finish_reason ==
"length"`, unparseable JSON, non-object JSON — returns a synthetic `WARN` carrying the reason rather
than crashing the stream. The dashboard must never go blank because the API hiccupped. Degraded
verdicts are `WARN` (never `OK`: don't claim health we didn't verify; never `ANOMALY`: our outage
isn't the monitored agent's fault) and carry `degraded: true` so the UI renders them differently.

---

## 4a. Why a per-step classifier isn't enough

The original design judged each trace event in isolation. That cannot detect two of the three
failure modes we claim to catch:

- **Infinite loops exist only across steps.** One `fetch_pricing` call is healthy. The same call
  three times is the bug. In isolation the third call is byte-identical to the first — there is no
  signal in the step itself.
- **Goal drift needs a goal.** Without knowing what the agent was asked to do, "drifted off-task"
  is not a judgement anyone can make, and a model asked to make it will confabulate one.

So the meta-agent receives, alongside the step:

1. **The session goal**, declared by the monitored agent via `POST /session/goal`. If it is not
   declared, the prompt says so explicitly — better an admitted blind spot than an invented goal.
2. **A bounded window of recent steps** (default 8, `SENTINEL_CONTEXT_WINDOW`) — tool, duration,
   error, verdict. Bounded because prompt cost is per request and a step from 200 calls ago is
   noise.
3. **A deterministic repeat count.** We fingerprint each call as `sha256(tool + input)` with sorted
   keys and count exact recurrences in the window *ourselves*, then hand the model that number as a
   fact.

Point 3 is the design principle worth defending: **deterministic where deterministic is possible,
LLM judgement only where judgement is actually required.** Counting is not a language problem. Asking
a model to notice that three JSON blobs are identical is strictly worse than computing it — slower,
costlier, and non-reproducible. The model's job is the part that genuinely needs semantics: is this
output consistent with this input, is the agent wandering.

Sorted-key hashing matters: without it, two identical calls whose kwargs happened to serialize in a
different order would fingerprint differently and the loop would go undetected.

---

## 5. Verdict semantics

| Verdict | Trigger | Detectable from | Color |
|---|---|---|---|
| `OK` | Valid tool call, output consistent with input, normal duration | the step | Green |
| `WARN` | Slow response, unusual input, minor inconsistency, meta-agent unavailable | the step | Amber |
| `ANOMALY` — hallucinated tool | Tool name not in the registry | the step + registry | Red |
| `ANOMALY` — exception | The step raised | the step | Red |
| `ANOMALY` — infinite loop | Identical call repeated in the window | **the window** | Red |
| `ANOMALY` — goal drift | Work diverging from the declared goal | **the goal** | Red |

The last two rows are why §4a exists — neither is visible in a single step.

Confidence threshold is configurable per deployment — this is the stated mitigation for the
false-positive misuse risk on the impact slide.

---

## 6. File layout

```
sentinelmind/
├── backend/
│   ├── decorator.py         # @monitor wrapper -> emits trace events
│   ├── session_context.py   # goal + rolling window + deterministic loop detection
│   ├── meta_agent.py        # trace + context -> Groq -> verdict
│   ├── audit_log.py         # stores every verdict; filter/export/clear
│   ├── app.py               # Flask + SocketIO server
│   └── demo_agent.py        # pipeline that triggers OK, WARN, ANOMALY
├── frontend/
│   └── index.html           # React (CDN) + vis.js live dashboard
├── evals/
│   ├── cases.py             # 9 labelled cases with rationales
│   └── run_eval.py          # accuracy, confusion matrix, p50/p95 latency
└── tests/
    ├── test_decorator.py
    ├── test_session_context.py
    ├── test_meta_agent.py
    ├── test_audit_log.py
    └── test_websocket.py
```

---

## 7. Test plan — 26 tests

> The deck says 15. It is now 26 — session-context logic, the offline replay path, the
> structured-output downgrade rules, and a prompt-integrity guard. One-word slide edit.

**test_decorator.py (4)** — calls the original function; emits a trace event; captures errors;
records duration.

**test_session_context.py (5)** — counts identical repeats and ignores different calls; fingerprint
is stable across key order; window is bounded; render carries goal/history/repeat count; render
admits drift is unassessable without a goal.

**test_meta_agent.py (8)** — returns `OK`; returns `ANOMALY`; handles API failure gracefully *without*
downgrading the format; downgrades only on a real 400 schema rejection and remembers it; an auth
failure never downgrades; `structured_output_mode` reports the resolved path; verdict has all
required fields; **the system prompt defines each verdict the right way round.** *(The Groq client is
faked — tests run offline, with no key, in under a second.)*

That last one is not defensive padding. File corruption inverted three sentences in the prompt —
"the step is valid" became "the step is not valid", and the ANOMALY definition was negated — which
told the model to produce backwards verdicts. Nothing failed: tests passed, the server ran, the
dashboard filled with confident wrong answers. **A prompt is behaviour, so it gets an assertion.**

**test_websocket.py (4)** — `/health` returns 200; `/audit` returns the correct structure; `/replay`
records a pre-judged verdict without touching the meta-agent; `/replay` rejects a payload with no
verdict.

**test_audit_log.py (5)** — records an entry; filters anomalies; exports valid JSON; clears the log;
handles multiple records.


### Evals — separate from tests, and the stronger claim

`python evals/run_eval.py` scores the meta-agent against **9 labelled cases** with written
rationales, using the real model and a shared `SessionContext` (the loop cases only read as a loop
in sequence). Reports accuracy, a 3×3 confusion matrix, and p50/p95 latency.

Tests prove the plumbing works with a fake model. The eval proves the *judgement* works with a real
one — and turns "under 3 seconds" from a claim into a measured p95. That distinction is the answer
to slide 4's "How you know it works: tests or evals."

---

## 8. Build order

1. `decorator.py` + `test_decorator.py` — the foundation; nothing works without trace events.
2. `audit_log.py` + `test_audit_log.py` — pure data, no external deps, fast to green.
3. `meta_agent.py` + `test_meta_agent.py` — the Claude call, mocked in tests.
4. `app.py` + `test_websocket.py` — wire the pieces onto a WebSocket.
5. `frontend/index.html` — the live graph.
6. `demo_agent.py` — scripted pipeline that reliably produces one of each verdict for the demo.
7. End-to-end run + `pytest tests/ -v`.

Rationale: bottom-up, each layer testable before the next depends on it. The demo agent is last
because it needs everything else to exist to be worth running.

---

## 9. Install & run

```bash
# A project venv, because no system Python on the build machine had the deps.
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

cp .env.example .env        # then paste your key from console.groq.com

cd backend && python app.py
# new terminal
python demo_agent.py --record   # live run; saves events AND verdicts to traces/

pytest tests/ -v          # 26 tests, offline, no key needed
python evals/run_eval.py  # scores the meta-agent against 9 labelled cases (needs a key)
```

**Record the fallback before demo day.** `--record` is what makes `--offline` possible; without a
recording that carries verdicts, offline mode refuses to run rather than replaying half a run.

```bash
python demo_agent.py --offline   # no provider call anywhere; survives dead wifi
```

`.env` is gitignored. Never commit a key — scrapers find them within minutes.

---

## 10. Scope & risk

**In scope:** trace capture, meta-agent verdicts, live dashboard, ANOMALY flagging with explanation,
structured audit log.

**Out of scope:** auto-correction injection — present as a disabled UI button so judges can see the
roadmap without us claiming it works.

**Fallback — two modes, covering different failures.** `--replay` re-sends recorded events; the
server still judges each one, so it survives a broken demo pipeline but not a dead network.
`--offline` replays recorded *verdicts* through `POST /replay`, which writes straight to the audit
log and the socket without touching the provider — that one survives dead wifi and a dead API.
`--record` now saves events *and* verdicts (pulled back from `GET /audit` after the run) so an
offline replay reproduces a real run rather than an approximation of one. Replayed verdicts carry
`replayed: true` and render with a `REPLAY` badge; passing a recording off as a live verdict would
corrupt the one artefact that is supposed to be the record of truth.

**Provider risk:** Groq's free tier is rate-limited, and its model lineup changes. `SENTINEL_MODEL`
makes a swap a one-line env change, and the `json_schema` → `json_object` downgrade means a model
with weaker structured-output support still works. If Groq is down entirely, `--replay` is the
answer — do not try to re-plumb a provider on demo morning.

**Known pitch gap:** *"LangSmith logs. SentinelMind intervenes."* — with auto-correction out of
scope, we detect and explain rather than act. Be ready for that question; the honest answer is that
real-time detection + explanation *is* the intervention enabler, and injection is the next step.

**After the hackathon:** open-source the decorator as a pip package.

---

## 11. Working rules

- Never push to GitHub without explicit approval.
- No `Co-Authored-By` trailer on commits.
- PLAN.md and PROGRESS.md stay current — plan changes land here, work log lands there.
