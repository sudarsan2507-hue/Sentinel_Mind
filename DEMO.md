# Demo runbook

Everything needed to record the demo video without improvising. Read once, run
the pre-flight, then follow the script.

**The single rule:** get a complete take recorded early. A rough video that
exists beats a perfect one still being edited at the deadline.

---

## Pre-flight — 3 minutes, do it every time

```bash
cd d:\Project\SentinelMind\Sentinel_Mind

.venv\Scripts\python.exe -m pytest tests/ -q          # expect: 151 passed
dir traces\last_run.json                              # must exist
```

Then start the server and confirm it is warm:

```bash
cd backend
..\.venv\Scripts\python.exe app.py
```

In another terminal:

```bash
curl http://127.0.0.1:5000/health
```

You want `"status": "ok"`. The warm-up runs at boot, so **wait for the
`Provider connection warmed.` line before recording** — otherwise the first
verdict on camera pays ~2.3s of connection setup and the first node sits grey
noticeably longer than the rest.

Open **http://127.0.0.1:5000** and clear any previous run with the **Clear**
button before you hit record.

---

## Which mode to demo in

| Mode | Command | Use when |
|---|---|---|
| **Live** | `python demo_agent.py` | The network is good and you want a genuinely live run |
| **Offline** ✅ | `python demo_agent.py --offline` | **Recommended for recording** |

**Record with `--offline`.** It replays verdicts captured from a real run, so
every take is byte-identical — a retake is not a fresh roll of the dice with a
live model. It needs no network, and it has been verified against a server
booted with a deliberately invalid API key.

Entries are badged `REPLAY` on the dashboard. That badge is deliberate and you
should not hide it: if asked, *"this is a recorded run replayed for a
reproducible demo — here is the same thing live"* is a completely fine answer,
and being caught passing a recording off as live is not.

If you want the live run on camera, record **that** take second, after the
offline take is safely in the can.

---

## The script — about 3 minutes

### 0:00 — The problem (20s)

> "AI agents fail silently. They loop, they invent tools they don't have, they
> drift off-task — and none of that throws an error. You find out later, reading
> logs. SentinelMind watches while it happens."

### 0:20 — The integration (15s)

Show `backend/demo_agent.py`, the decorator on one function.

> "One decorator. That's the entire integration. Every call now emits a trace
> event and gets judged."

### 0:35 — Start the run (10s)

```bash
python demo_agent.py --offline
```

> "Here's a support agent answering: has my refund window expired?"

### 0:45 — Green, then amber (25s)

Point at the first two nodes going green.

> "Looked up the policy, loaded the account. Both fine."

Third node goes amber.

> "This one succeeded — but it took 30 times longer than normal. Nothing
> failed, so nothing would appear in an error log. We flagged it anyway."

### 1:10 — The hallucinated tool (20s)

> "Now it tries to delete a customer record. Two problems: that tool isn't in
> its registry — it invented the capability — and nobody asked it to delete
> anything. Red."

### 1:30 — **The loop. This is the moment.** (45s)

Slow down here. This is the strongest 45 seconds in the video.

⚠️ **What is actually on screen:** all three loop calls come back **red**, and
the explanation on the second and third names the loop directly — *"called with
the same input multiple times in a row, indicating a potential infinite loop."*
They do **not** escalate green→amber→red in this run, because an ANOMALY is
already in the session window by the time the loop starts. Narrate what is
there, not an escalation the viewer cannot see.

> "Watch these next three. They are the *same call* — same tool, same input,
> byte-identical. And read the explanation: it says the call has been repeated
> with the same input, indicating a loop."
>
> "Here's why that's hard. Any one of those calls, on its own, looks perfectly
> healthy — doing something once is normal. A system that judges one step at a
> time has no way to know: it sees three identical healthy-looking calls and
> says 'fine' three times.
>
> Ours catches it because it remembers the run. And the repeat count isn't
> guessed by the model — we hash the call and count it in plain code, then hand
> the model that number as a fact. Counting isn't a language problem."

**Optional, if you want the escalation on camera:** it shows up cleanly in the
eval, where the loop cases run against a clean window. Cut to a terminal
running `python evals/run_eval.py`:

```
loop_call_1   OK        conf 1.00
loop_call_2   WARN      conf 0.70    <- confidence dips exactly where it should
loop_call_3   ANOMALY   conf 0.95
```

> "Same call three times, in isolation: OK, then warn, then anomaly. The only
> thing that changed is how many times we'd seen it."

That is the single most persuasive frame in the project — but it is the eval,
not the dashboard. Do not describe one while showing the other.

### 2:15 — The swallowed error (15s)

> "Last step, a service fails and the agent hides the error. We caught it
> anyway."

### 2:30 — Close (20s)

> "Nine steps, every verdict under a second, each with a plain-English reason.
> Finding this in logs takes ten minutes — and the loop, you'd probably never
> spot at all."

---

## What to say, precisely

Wording that survives a judge checking it:

| Say this | Not this |
|---|---|
| "8 of 9 on our labelled set" | "89% accurate" |
| "p95 1.43 seconds, measured" | "under 3 seconds" |
| "JSON mode enforced by the API" | "strict schema enforcement" |
| "We detect and explain in real time" | "SentinelMind intervenes" |
| "The memory loop is built; its effect is our next measurement" | "It learns and improves" |

The last two matter most. Auto-correction is **out of scope** — the button is
on the dashboard, deliberately disabled. And the learning loop works
mechanically but its effect on failure rate has never been measured cleanly.

If a judge presses on the tagline: *"Fair catch. Today we detect and explain.
Intervention is the next step, and it's only possible because detection is fast
enough to act on — you can't interrupt an agent on information that arrives ten
minutes late."*

---

## If something breaks

| Symptom | Fix |
|---|---|
| Dashboard blank / "Disconnected" | Server isn't running. Start it, refresh. |
| Nodes stay grey | Verdicts aren't landing — switch to `--offline`. |
| `No recorded trace at ...` | `python demo_agent.py --record` while online. |
| Rate limited / 429 | `--offline`. Makes no provider call at all. |
| Nodes from a previous take | **Clear** button, or `POST /audit/clear`. |
| Everything is broken | `--offline` with the server up. It is the floor. |

**`--offline` is the floor.** It survives dead wifi, a dead provider, an
exhausted quota, and a broken pipeline. If it is running, you have a demo.

---

## Known gaps — say them before you're asked

- **No auto-correction.** Detect and explain only.
- **The learning loop is unproven.** Built and verified working; effect
  unmeasured. Do not claim it reduces failures.
- **Nine eval cases** is a demonstration, not a generalisation.
- **The knowledge graph has no UI yet** — it is real and tested, but it lives
  in `/knowledge` and the terminal. Show it with a `curl` if asked, or skip it.
- **LangChain is not wired.** `@monitor` is framework-agnostic, but that path
  is not written or tested.

Naming a limitation before a judge finds it is what makes the rest of the
numbers credible.
