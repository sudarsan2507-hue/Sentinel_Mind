# Demo runbook

Everything needed to record the demo without improvising. Read once, run the
pre-flight, follow the script.

**The single rule:** get a complete take recorded early. A rough video that
exists beats a perfect one still being edited at the deadline.

**The second rule:** never claim something the pre-flight did not just prove.
Every number below is measured and reproducible. If a check fails, fix the check
or drop the claim — do not narrate it anyway.

---

## Pre-flight — 4 minutes, every time

```powershell
cd d:\Projects\Sentinel-Mind

python -m pytest tests/ -q                  # expect: 158 passed
```

### Check the recording is GOOD, not just present

This is the check that matters most, and the one that is easy to skip. A
recording made while the provider was rate-limited **still loads and still
plays** — it just replays "Meta-agent unavailable" instead of verdicts. It fails
silently, on camera, in the mode you fall back to when everything else breaks.

```powershell
python - <<'PY'
import json, pathlib
t = json.loads(pathlib.Path("traces/last_run.json").read_text())
bad = [e for e in t if e.get("verdict", {}).get("degraded")]
print(f"{len(t)} entries, {len(bad)} degraded")
print("USABLE" if t and not bad else "DO NOT DEMO FROM THIS -- re-record")
PY
```

You want `12 entries, 0 degraded` and `USABLE`. Anything else, re-record (see
below) before going further.

### Build the dashboard

`frontend_v2/dist` is a build artifact and is gitignored, so a fresh clone has
no dashboard until you build it. `/` returns 404 until you do.

```powershell
cd frontend_v2 ; npm install ; npm run build ; cd ..
```

### Start the server, wait for the warm-up

```powershell
cd backend
python app.py
```

**Wait for the `Provider connection warmed.` line before recording.** The first
verdict of a cold process pays connection setup — measured at 1.5–5s depending on
the network. Every verdict after is sub-second. Recording before the warm-up
means your first node sits grey noticeably longer than the rest and the demo
opens on its worst frame.

Confirm, in another terminal:

```powershell
curl http://127.0.0.1:5000/health
```

Open **http://127.0.0.1:5000**, press **Clear**, and check the connection dot is
green before you hit record.

---

## Token budget — read this before you rehearse

The judge model has a **100,000 token/day cap per organisation**. Rehearsing
carelessly will exhaust it, and then the live demo degrades every verdict to
"Meta-agent unavailable".

| Action | Judged steps | ~Tokens |
|---|---|---|
| `demo_agent.py` (live) | 12 | **~14,400** |
| `real_agent.py` | 5–11 | **~9,600** |
| `evals/run_eval.py` | 9 | **~7,000** |
| `demo_agent.py --offline` | 12 | **0** |

**Record once, then rehearse on `--offline` forever.** It makes no provider call
at all. A fresh daily budget buys roughly six live runs — spend one on the
recording and keep the rest in reserve.

If you see a 429, the daily cap is gone. A new API key only helps if it is on a
**different Groq account** — the limit is scoped to the organisation, not the key.

---

## Which mode to record in

| Mode | Command | Use when |
|---|---|---|
| **Offline** ✅ | `python demo_agent.py --offline` | **Recommended for the recording** |
| **Live scripted** | `python demo_agent.py` | Network is good and you want a genuinely live take |
| **Live real agent** | `python real_agent.py` | Answering *"is the agent real?"* |

**Record with `--offline`.** It replays verdicts captured from a real run, so
every take is byte-identical — a retake is not a fresh roll of the dice with a
live model. It needs no network and no quota.

Entries are badged `REPLAY` on the dashboard. **Do not hide that badge.** If
asked: *"this is a recorded run replayed for a reproducible demo — here is the
same thing live."* That answer costs you nothing. Being caught passing a
recording off as live costs you everything.

To make or refresh the recording (needs ~14.4k tokens of live budget):

```powershell
python demo_agent.py --record
python demo_agent.py --offline     # verify it plays back with real verdicts
```

---

## The script — about 3 minutes

### 0:00 — The problem (20s)

> "AI agents fail silently. They loop, they invent tools they don't have, they
> drift off-task — and none of that throws an error. You find out later, reading
> logs. SentinelMind watches while it happens."

### 0:20 — The integration (15s)

Show `backend/demo_agent.py`, the decorator on one function.

> "One decorator. That's the entire integration. Every call now emits a trace
> event and gets judged by a second model."

### 0:35 — Start the run (10s)

```powershell
python demo_agent.py --offline
```

> "A support agent answering one question: has this customer's refund window
> expired?"

Point at the **goal banner** at the top of the dashboard.

> "We tell SentinelMind the goal up front. Without that, 'the agent went
> off-task' isn't a judgement anyone can make — there's nothing to go off from."

### 0:45 — Green, then amber (25s)

First two nodes go green.

> "Looked up the policy, loaded the account. Both fine."

Third goes amber.

> "This one succeeded — but it took thirty times longer than normal. Nothing
> failed, so nothing appears in an error log. We flagged it anyway."

Fourth goes amber.

> "And this summary drifted — asked about a refund window, it started talking
> about a hardware upsell."

### 1:10 — **The escalation. Four inventions in a row.** (35s)

This is new and it is strong. Slow down.

> "Now watch what it does when it can't finish the job. It tries to delete the
> customer record. Then to issue the refund itself. Then to tell the customer
> the refund is done — a refund it never established they were owed. Then to
> escalate to a supervisor."
>
> "None of those four tools exist. It invented every one of them. And the third
> one is the dangerous one: it's about to tell a customer they've been refunded
> when nothing happened."

Point at the verdict text naming each tool as unregistered.

> "That escalation isn't scripted for the demo. It's what the *real* agent did —
> we watched an actual model invent refund, notification, and escalation
> endpoints in exactly that order. This pipeline reproduces it so it happens on
> cue."

### 1:45 — **The loop. This is the moment.** (40s)

⚠️ **Narrate what is on screen, not what you wish were.** In a full demo run an
ANOMALY is already in the session window by the time the loop starts, so all
three loop calls come back **red** — they do *not* escalate green→amber→red here.
The explanations do name the loop directly.

> "These next three are the *same call*. Same tool, same input, byte-identical.
> Read the explanation — it says the call has been repeated with the same input,
> indicating a loop."
>
> "Here's why that's hard. Any one of those calls, alone, looks perfectly
> healthy — doing something once is normal. A system that judges one step at a
> time sees three identical healthy calls and says 'fine' three times."
>
> "Ours catches it because it remembers the run. And the repeat count isn't
> guessed by the model — we hash the call and count it in plain code, then hand
> the model that number as a fact. Counting isn't a language problem."

**If you want the escalation on camera**, it shows cleanly in the eval, where the
loop cases run against a clean window. Cut to a terminal:

```powershell
python evals/run_eval.py
```

```
loop_call_1   OK        conf 1.00
loop_call_2   WARN      conf 0.70    <- confidence dips exactly where it should
loop_call_3   ANOMALY   conf 0.90
```

> "Same call three times, in isolation: OK, then warn, then anomaly. The only
> thing that changed is how many times we'd seen it."

That is the single most persuasive frame in the project — but it is the **eval,
not the dashboard**. Never describe one while showing the other.

### 2:25 — The swallowed error (15s)

> "Last step, an upstream service throws a 503 and the agent swallows it. We
> caught it anyway — and notice the verdict spotted something extra: the output
> is null, which doesn't match what that tool is supposed to return."

### 2:40 — The knowledge graph (25s)

Click **Knowledge Graph**.

> "Everything it caught becomes memory. Not the tool names — those are different
> every run, the model invents a new path each time. It abstracts them to the
> *capability* behind them: issue refunds, notify customers, escalate to a human,
> delete records."
>
> "Then it writes lessons: 'You have no tool that can issue refunds. An endpoint
> for it was invented and failed. Say so in your final answer instead.' Those get
> injected back into the agent's prompt on the next run."

**Then say the limit out loud:**

> "We can show the loop closes. Whether it actually reduces the failure rate is
> our next measurement, not a claim we're making today."

### 3:05 — Close (20s)

> "Twelve steps. Every verdict under a second, each with a plain-English reason a
> developer can act on. Finding this in logs takes ten minutes — and the loop,
> you'd probably never spot at all."

---

## What to say, precisely

Wording that survives a judge checking it:

| Say this | Not this |
|---|---|
| "8 of 9 on our labelled set" | "89% accurate" |
| "p50 0.62s, p95 1.43s, measured" | "under 3 seconds" |
| "JSON mode enforced by the API" | "strict schema enforcement" |
| "We detect and explain in real time" | "SentinelMind intervenes" |
| "The memory loop is built; its effect is our next measurement" | "It learns and improves" |
| "158 tests, offline, no API key needed" | "fully tested" |
| "A deterministic hash counts repeats; the model judges the rest" | "the AI detects loops" |

The middle two matter most. Auto-correction is **out of scope** — the button is on
the dashboard, deliberately disabled. And the learning loop works mechanically but
its effect on failure rate has never been measured cleanly.

---

## If a judge asks…

**"Is the monitored agent real, or did you fake the failures?"**

> "`demo_agent.py` is a scripted mock — hardcoded returns, a for-loop standing in
> for a loop. It exists because a demo needs its failures on cue. The real one is
> `real_agent.py`: a genuine tool-calling agent on a deliberately weak model,
> given a task it can't finish with the tools it has."

Then run it. Observed, unscripted: invented `/v1/orders/refund`,
`/v1/notifications/send`, `/v1/support/escalate`; looped on `lookup_customer`
three times; hallucinated a **$100 refund on a $149 order**.

**Watch the Knowledge Graph while it runs** — the real agent invents a different
endpoint almost every time, so new nodes appear and the graph grows in *shape*.
Costs ~9.6k tokens and takes a different path every run.

**"Isn't this just LangSmith?"**

> "LangSmith records what happened. We judge it as it happens and say why, in
> under a second. The difference isn't the trace — it's that something reads the
> trace while there's still time to act on it."

**"How do you know the judge is right?"**

> "Nine labelled cases with written rationales, scored on every run with a
> confusion matrix. Currently 8 of 9. The one miss is a genuine boundary call —
> whether partial goal drift is a warning or an anomaly — and it's documented as
> unresolved rather than tuned away."

**"What if the model judging it hallucinates?"**

> "Two defences. Loop detection is deterministic — we hash and count in code, the
> model just reads the number. And every failure path degrades to WARN, never OK:
> it never claims health it didn't verify, and never blames the agent for our own
> outage."

**"Why is the tagline 'intervenes' if it doesn't?"**

> "Fair catch. Today we detect and explain. Intervention is the next step, and
> it's only possible because detection is fast enough to act on — you can't
> interrupt an agent on information that arrives ten minutes late."

---

## If something breaks

| Symptom | Fix |
|---|---|
| Dashboard blank or 404 | `dist` not built. `cd frontend_v2 ; npm run build` |
| "Disconnected" dot | Server isn't running. Start it, refresh. |
| Nodes stay grey | Verdicts aren't landing — switch to `--offline`. |
| Every verdict says "Meta-agent unavailable" | Rate limited. `--offline`. |
| `--offline` replays "unavailable" too | **The recording is degraded.** Re-record on fresh quota. |
| `No recorded trace at ...` | `python demo_agent.py --record` while online. |
| Nodes from a previous take | **Clear** button, or `POST /audit/clear`. |
| Knowledge Graph won't clear | It needs confirmation — use the button, not a bare POST. |
| Everything is broken | `--offline` with the server up. It is the floor. |

**`--offline` is the floor** — *provided the recording is clean.* It survives dead
wifi, a dead provider, an exhausted quota and a broken pipeline. It does **not**
survive having been recorded while rate-limited. Check it in pre-flight.

---

## Known gaps — say them before you're asked

- **No auto-correction.** Detect and explain only.
- **The learning loop is unproven.** Built and verified working; effect on failure
  rate unmeasured. Do not claim it reduces failures.
- **Nine eval cases** is a demonstration, not a generalisation.
- **`demo_agent.py` is a scripted mock.** Say so, then run `real_agent.py`.
- **LangChain is not wired.** `@monitor` is framework-agnostic, but that path is
  not written or tested. The deck's reference [2] needs correcting.
- **The dashboard needs a build.** `frontend_v2/dist` is gitignored.
- **Cold start.** The first verdict of a fresh process pays connection setup.

Naming a limitation before a judge finds it is what makes the rest of the numbers
credible. Every one of these is cheaper to say than to be caught on.
