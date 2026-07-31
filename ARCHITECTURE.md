# SentinelMind — Architecture & Technical Reference

What every piece is, what it does, and **why it works the way it does**. The
"why" matters more than the "what" here — several decisions look arbitrary until
you know the failure they prevent.

Companion docs: [README](README.md) (what it is) · [PLAN](PLAN.md) (design
decisions) · [PROGRESS](PROGRESS.md) (what is verified) · [DEMO](DEMO.md) (runbook).

---

## 1. Tech stack

### Runtime

| | Version |
|---|---|
| Python | 3.14.2 |
| Node | 24.13.0 |

### Backend

| Package | Version | Role |
|---|---|---|
| `Flask` | 3.1.3 | HTTP server, trace ingest, audit API |
| `Flask-SocketIO` | 5.6.1 | WebSocket push of verdicts to the dashboard |
| `python-socketio` / `python-engineio` | 5.16.3 / 4.13.3 | Socket.IO transport |
| `openai` | 2.50.0 | Client for Groq's OpenAI-compatible endpoint |
| `python-dotenv` | 1.2.1 | Loads `GROQ_API_KEY` from `.env` |
| `requests` | 2.32.5 | Monitored agents POST their traces |
| `pytest` | 9.0.2 | 158 tests, fully offline |

**No LLM framework.** No LangChain, no agent library. The tool-calling loop in
`real_agent.py` is hand-written — see §7 for why that was deliberate.

### Frontend

| Package | Version | Role |
|---|---|---|
| `react` / `react-dom` | 19.2.7 | UI |
| `react-router-dom` | 7.18.2 | `/`, `/dashboard`, `/graph` |
| `socket.io-client` | 4.8.3 | Live verdict stream |
| `tailwindcss` + `@tailwindcss/vite` | 4.3.3 | Styling |
| `framer-motion` | 12.43.0 | Node/feed animation |
| `lucide-react` | 1.28.0 | Icons |
| `vite` | 8.1.1 | Build |

### Models

| Role | Model | Why |
|---|---|---|
| **Meta-agent** (the judge) | `llama-3.3-70b-versatile` | Judgement quality. Overridable via `SENTINEL_MODEL`. |
| **Monitored agent** (the subject) | `llama-3.1-8b-instant` | Weak *on purpose* — see §7. |

Both on Groq, chosen for LPU inference speed: the product claim is a sub-second
verdict, and a verdict is a short classification rather than a reasoning problem.

---

## 2. Module map

```
backend/
  decorator.py         124   @monitor — trace capture + subscriber bus
  session_context.py   134   goal + rolling window + deterministic repeat hashing
  meta_agent.py        443   trace + context -> Groq -> verdict
  knowledge_graph.py   368   failures -> capability graph -> lessons
  audit_log.py         108   thread-safe verdict store
  app.py               341   Flask + SocketIO, 13 routes, worker thread
  demo_agent.py        366   scripted subject (deterministic, for stage)
  real_agent.py        413   real tool-calling subject (genuine failures)

tests/                 1903  158 tests, no network, no API key
```

---

## 3. Request flow — one step, end to end

```
   monitored agent calls a @monitor-wrapped function
              │
              ▼
   decorator.py  times it, builds the event, re-raises any exception untouched
              │  {id, tool, step_type, input, output, error, duration_ms, timestamp}
              ▼
   POST /trace ─────────────────► returns 202 in <1ms, queues the event
              │                    (never blocks the agent being watched)
              ▼
   worker thread (single)
              │
              ├─ session_context.render(event)
              │     goal + last N steps + DETERMINISTIC repeat count
              ▼
   meta_agent.evaluate(event, context)
              │     Groq, temperature 0, JSON schema enforced by the API
              ▼
   verdict {status, explanation, confidence, latency_ms, degraded, usage}
              │
              ├─ session.record(event, verdict)   ← AFTER judging (§5.2)
              ├─ audit_log.record(...)
              ├─ knowledge_graph.ingest(...)      ← only non-OK, non-degraded
              └─ socketio.emit("verdict" | "learned" | "summary")
                                                   │
                                                   ▼
                                          React dashboard recolours the node
```

---

## 4. HTTP + WebSocket surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trace` | Submit one trace event. Returns **202** immediately. |
| `POST` | `/replay` | Push a **pre-judged** entry straight to the log (offline mode). |
| `POST` | `/session/goal` | Declare the task. Resets the window, starts a run. |
| `GET` | `/session` | Current goal + rolling window. |
| `GET` | `/knowledge` | Graph nodes, edges, derived lessons. |
| `GET` | `/knowledge/lessons` | What `--learn` fetches before acting. |
| `POST` | `/knowledge/clear` | Wipe memory. **Requires `{"confirm": true}`.** |
| `GET` | `/audit` | Full log. `?status=ANOMALY` filters. |
| `GET` | `/audit/export` | Log as a downloadable JSON file. |
| `POST` | `/audit/clear` | Reset between runs. |
| `GET` | `/health` | Liveness + resolved model. |
| `GET` | `/`, `/<path>` | Built React app, with SPA fallback. |

**Socket events pushed:** `trace` (draw the node grey immediately), `verdict`,
`summary`, `learned`, `goal`, `cleared`, `knowledge_cleared`.

---

## 5. The logic that matters

### 5.1 Observing must never change what it observes

`@monitor` re-raises every exception untouched and returns the original value
unmodified. Subscriber failures are swallowed **per handler** so a broken
consumer cannot take down the agent being watched.

> A monitoring tool that alters the thing it monitors isn't monitoring, and one
> that crashes the host is worse than no monitoring at all.

### 5.2 Record the step *after* judging it

```python
verdict = meta_agent.evaluate(event, context=session)
session.record(event, verdict)          # after, not before
```

Record first and every step appears in its own lookback window, counts as its own
repeat, and **every call looks like a loop.** An off-by-one here doesn't crash —
it silently makes the product wrong.

### 5.3 Trace ingest is non-blocking

`POST /trace` queues and returns `202` in under a millisecond. Judging takes
~600ms. If the POST blocked, SentinelMind would slow the agent it watches by
600ms *per step*. Observation has to be free.

### 5.4 Loops and drift cannot be seen one step at a time

This is the core architectural argument.

- **A loop exists only across steps.** The third identical call is byte-identical
  to the first. There is no signal in the step itself.
- **Drift needs a declared goal.** Without one, "went off-task" is unfalsifiable,
  and a model asked to judge it will invent a goal to judge against.

So the judge receives, with every step: the session goal, a bounded window of
recent steps, and a repeat count.

### 5.5 Deterministic where deterministic is possible

```python
fingerprint = sha256(json.dumps({"tool":…, "input":…}, sort_keys=True))[:16]
```

The repeat count is computed **in code** and handed to the model as a fact. The
model is told to trust it.

> Counting is not a language problem. Asking a model to notice three JSON blobs
> are identical is slower, costs tokens, and gives a different answer each run.
> The model's job is the part that genuinely needs semantics.

`sort_keys=True` is load-bearing: without it two identical calls whose kwargs
serialised in a different order would hash differently and the loop would go
undetected.

The window is **bounded** (default 8, `SENTINEL_CONTEXT_WINDOW`) so prompt cost
stays flat on a long run — and a step from 200 calls ago is noise, not signal.

### 5.6 Every failure degrades to WARN — never OK, never ANOMALY

| Choice | Reason |
|---|---|
| Never `OK` | Don't claim health you didn't verify |
| Never `ANOMALY` | Our outage is not the monitored agent's fault |
| Always `degraded: true` | The UI must distinguish "agent is fine-ish" from "we couldn't look" |

This is why the whole system runs end-to-end **without an API key** — it never
crashes, it just reports that it couldn't look.

**The trap this creates:** degraded verdicts are always WARN and *can never be
ANOMALY*, so a rate-limited run scores **zero anomalies and looks perfect**. That
produced a false "anomalies fell 100%" result once. Both `run_eval.py` and
`run_learning_experiment.py` now refuse to report any number when a step went
unjudged.

### 5.7 Bounded backoff — a stall is worse than a fast failure

Judging is single-threaded, so a sleep stalls the whole queue.

- **Short rate limit** → wait it out. Degrading on the first 429 blinds the
  monitor for the rest of the burst.
- **Long rate limit** → give up immediately. Retrying a wait you cannot outlast
  costs `max_backoff × retries` and fails anyway.

`_retry_after` reads the `Retry-After` header, then falls back to parsing the
figure out of the message body (`"Please try again in 9m37.152s"` — where Groq
reports it on daily-cap errors and the header is absent). If the required wait
exceeds `max_backoff` (5s), degrade now.

> Measured before the fix: 90,659 ms for one verdict, still degraded, with a
> 13-step run frozen at a single result.

### 5.8 JSON enforced by the API, never by prompting

`response_format` with a JSON schema. If a model rejects strict schema, downgrade
**once** to `json_object` and cache that on the instance, so a model swap can't
break a run mid-demo.

> No regex over model output, ever.

### 5.9 The confidence threshold

`SENTINEL_CONFIDENCE_THRESHOLD` downgrades a low-confidence `ANOMALY` to `WARN`.
This is the stated mitigation for false-positive alert fatigue: raise it and only
high-confidence anomalies page you.

---

## 6. The knowledge graph

### Shape

```
(tool)       --exhibits-->  (failure_mode)     how this call went wrong
(tool)       --requires-->  (capability)       what it was reaching for
(capability) --missing_in--> (goal)            the gap that caused it
```

Edges carry occurrence counts, so lessons rank by **how often a mistake recurs**
rather than by how recent it is.

### Why it abstracts to capabilities

Observed across baseline runs of the *same* task, the real agent invented:

```
run 1:  /v1/orders/refund   /v1/orders/refund-status   /v1/notifications/send
run 2:  /v1/orders/refund   /v1/customers/notifications
run 3:  /v1/orders/refund   /v1/orders/notification    /v1/support/escalate
```

The **capability** is stable — refund, notify, escalate. The **exact path is
different almost every time.** A store keyed on literal tool names would memorise
strings that never recur and generalise nothing.

So endpoints are classified into capability nodes by keyword, and lessons are
written about capabilities. *"You have no way to issue refunds"* transfers to the
next run. *"`/v1/orders/refund` returned 403"* does not.

### Classification refuses to guess

`classify_capability` returns a sentinel when nothing matches, rather than
inventing a plausible name. Lesson text special-cases it and names the **tools**
instead — the part we actually know.

> An earlier template rendered the sentinel literally: *"You have NO tool that can
> an unrecognised capability."* Ungrammatical, and it asserted a capability gap
> that was never established. That text goes into an agent's system prompt.

### What is remembered

Only **non-OK, non-degraded** verdicts. A degraded verdict means we could not
look; remembering it would teach a lesson about our own outage rather than about
the agent.

A step can exhibit more than one mode — an unregistered tool that *also* raised is
both a hallucination and an exception — so both edges are recorded, not just the
primary one.

### The loop back into the agent

`real_agent.py --learn` fetches `/knowledge/lessons` and prepends the block to its
own system prompt.

> **This is retrieval-augmented prompting over accumulated failure memory. It is
> NOT training — no weights change.** Whether it reduces the failure rate is an
> open empirical question measured by `evals/run_learning_experiment.py`, not a
> claim the project makes.

---

## 7. Two monitored subjects, on purpose

| | `demo_agent.py` | `real_agent.py` |
|---|---|---|
| Nature | Scripted mock | Real tool-calling agent |
| Model | none | `llama-3.1-8b-instant` |
| Failures | Planted, deterministic | Genuine, different every run |
| Use | On stage — failures on cue | Proving the tool works |

**Why the subject model is deliberately weak:** a monitoring tool that only works
on frontier models is not much of a monitoring tool, and cheap models are what
actually get deployed.

**Why the task is impossible:** the agent is asked to determine refund
eligibility *and then issue the refund and notify the customer* — with read-only
tools. What it does when cornered is its own choice.

**Why `call_internal_api` is an open dispatcher:** the endpoint is a free-text
argument rather than a fixed schema, mirroring a real internal gateway or MCP
server. That lets the agent invent capabilities — and an invented endpoint reaches
SentinelMind as a tool name absent from the registry, which is a **real**
hallucination rather than a simulated one.

**Why no LangChain:** `AgentExecutor` validates tool names and would have
*blocked* the hallucinated endpoints — hiding the exact behaviour the project
exists to demonstrate. A hand-written loop keeps the failure observable.

Observed unscripted, across runs: invented `/v1/orders/refund`,
`/v1/notifications/send`, `/v1/support/escalate`; looped on `lookup_customer`
three times; hallucinated a **$100 refund on a $149 order**.

---

## 8. Offline mode — the two fallbacks differ

| Mode | Skips the pipeline | Survives dead network |
|---|---|---|
| `--replay` | ✅ | ❌ still calls the provider to re-judge |
| `--offline` | ✅ | ✅ replays recorded **verdicts** to `/replay` |

`--offline` writes straight to the audit log and socket. Nothing leaves the
machine. Entries are badged `replayed` on the dashboard — a recorded verdict shown
as a live one would be a lie, and the audit log is meant to be the record of truth.

> **A recording made while rate-limited still loads and still plays** — it just
> replays "Meta-agent unavailable". It fails *silently*, in the mode you fall back
> to when everything else has broken. Check for degraded entries before trusting it.

---

## 9. Measurement

| Harness | Measures | Status |
|---|---|---|
| `tests/` (158) | Behaviour, offline, no API key | ✅ passing |
| `evals/run_eval.py` | Verdict accuracy vs 9 labelled cases + p50/p95 latency | ✅ 8/9, p50 0.62s, p95 1.43s |
| `evals/run_learning_experiment.py` | Does memory reduce failures? | ⏳ **unmeasured** |

Both eval harnesses **refuse to print a number when any step went unjudged** —
§5.6 explains why a rate-limited run would otherwise score perfectly.

Each case in `evals/cases.py` carries a written rationale, so a disagreement is a
discussion about the label rather than a mystery.

**On isolating variables:** the first version of the loop cases used an off-goal
tool *and* ran immediately after an ANOMALY, so a wrong verdict couldn't be
attributed to any single cause. Fixed by changing the **inputs**, not the labels —
relabelling until the model agrees is how an eval stops meaning anything.

---

## 10. Configuration

| Variable | Default | Effect |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Free at console.groq.com |
| `SENTINEL_MODEL` | `llama-3.3-70b-versatile` | Judge model |
| `SENTINEL_AGENT_MODEL` | `llama-3.1-8b-instant` | Subject model |
| `SENTINEL_CONTEXT_WINDOW` | `8` | Steps retained for loop/drift detection |
| `SENTINEL_CONFIDENCE_THRESHOLD` | `0.0` | ANOMALY below this → WARN |
| `PORT` | `5000` | Server port |

Rate limits are **per organisation**, not per key: a second key on the same
account shares the same exhausted budget.

---

## 11. Known limits

- **No auto-correction.** Detect and explain only; the button is deliberately disabled.
- **The learning loop's effect is unmeasured.** Built and verified working — that is not the same claim.
- **Nine eval cases** is a demonstration, not a generalisation.
- **`temperature=0` is not determinism.** LLM inference varies run to run; report ranges.
- **LangChain is not wired.** `@monitor` is framework-agnostic, but that path is untested.
- **`frontend_v2/dist` is gitignored** — a fresh clone needs `npm install && npm run build`.
- **Cold start** — the first verdict of a fresh process pays connection setup.
