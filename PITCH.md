# SentinelMind — presentation script

Evaluation round. Full script, timed for **6 minutes**, with a 3-minute cut and
a Q&A bank at the end.

Every number here is measured and traceable to `evals/results/`. Nothing in
this script overstates the build — that is deliberate, and it is what makes the
rest of it credible.

---

## THE SPINE — if you remember nothing else

1. AI agents fail **silently**.
2. We judge every step **live**, in under a second, with a reason.
3. Some failures exist **only across steps** — that's the hard part, and it's what we solved.
4. We compute what's computable; the model only judges what needs judgement.
5. We're honest about what we haven't proven.

---

# THE SCRIPT

## [0:00–0:35] Open — the problem

> "Everyone here is building with AI agents. So here's a question: when your
> agent goes wrong, how do you find out?
>
> Not when it *crashes* — crashes are easy. I mean when it quietly does the
> wrong thing. It loops on the same call twenty times. It reaches for a tool it
> doesn't have and invents one. It slowly forgets what you asked it to do.
>
> None of that throws an error. Your logs look perfect. You find out
> later — reading through traces, if you happen to go looking.
>
> **LangSmith and Langfuse record all of it, faithfully, and tell you
> afterwards. We built the thing that tells you now.**"

*Pause. Let that land.*

---

## [0:35–1:00] What it is

> "SentinelMind is an AI agent that monitors other AI agents, in real time.
>
> Think of it as the difference between **CCTV and a security guard.** The
> camera records everything perfectly — and shouts at nobody. The guard notices,
> and says something while it's happening.
>
> Every step your agent takes gets judged by a second model, in under a second,
> with a plain-English explanation of what's wrong."

---

## [1:00–1:25] The integration — show the code

*Show `backend/demo_agent.py`, one decorated function.*

> "This is the entire integration. One decorator on a function.
>
> No framework to adopt, no SDK, no config file. Your function does exactly what
> it did before — same return value, same exceptions, untouched. It just also
> emits a trace event now.
>
> That was a deliberate constraint: a monitoring tool that changes the behaviour
> of the thing it monitors isn't monitoring."

---

## [1:25–2:45] The demo

*Run `python demo_agent.py --offline`. Dashboard visible.*

> "A support agent answering: *has my refund window expired?*
>
> Nodes appear grey the instant a step happens, then recolour when the verdict
> lands. Watch."

**Green (2 nodes)**
> "Looked up the refund policy. Loaded the customer's account. Both healthy —
> on-task, sensible output, normal latency."

**Amber**
> "This one is interesting. The pricing call **succeeded** — no error, nothing in
> a log anywhere. But it took 2.4 seconds against a 60-millisecond baseline.
> Nothing failed, so nothing would ever alert you. We flagged it anyway."

**Amber**
> "Asked to summarise a refund question, it produced a summary about upselling
> hardware. Off-task — the beginning of drift."

**Red**
> "Now it tries to **delete a customer record.** Two things wrong: that tool
> isn't in its registry — it invented the capability — and nobody asked it to
> delete anything. It's a read-only task."

**Red ×3 — SLOW DOWN HERE**
> "And now the important one. These next three calls are **identical.** Same
> tool, same input, byte-for-byte.
>
> Read the explanation: *'called with the same input multiple times in a row,
> indicating a potential infinite loop.'*
>
> Here's why that's genuinely hard. Look at any one of those calls on its own —
> it's perfectly healthy. Calling a pricing API once is normal. A system that
> judges one step at a time sees three healthy-looking calls and says 'fine'
> three times. It has no other information.
>
> We catch it because we remember the run."

**Red — final**
> "Last step: a service fails, and the agent **swallows the error** and carries
> on. We caught it anyway."

---

## [2:45–3:30] The idea worth defending

*This is the technical heart. Say it slowly.*

> "So how do we catch a loop? The obvious answer is: ask the model, 'is this a
> loop?' **We don't do that.**
>
> We hash every call — tool plus input, with sorted keys — and count exact
> repeats **in plain Python.** Then we hand the model that number as a *fact*
> and ask the question that actually needs a mind: *given this has happened
> twice already, is this healthy?*
>
> **Deterministic where deterministic is possible. LLM judgement only where
> judgement is genuinely required.**
>
> Counting isn't a language problem. Asking a model to notice three JSON blobs
> are identical is slower, more expensive, and gives you a different answer on
> Tuesday. Computing it is exact, free, and reproducible."

**If you have the eval on screen, this is the moment:**

```
loop_call_1   OK        conf 1.00
loop_call_2   WARN      conf 0.70
loop_call_3   ANOMALY   conf 0.95
```

> "Same call, three times, against a clean session. OK, then warn, then anomaly.
> The **only** thing that changed is how many times we'd seen it. Confidence
> dips to 0.70 exactly where a human would hesitate — on the second one, where
> it might still be a retry."

---

## [3:30–4:15] Results — measured, not claimed

> "Numbers, and I'll be precise about what they mean.
>
> **Verdict latency: p50 0.62 seconds, p95 1.43 seconds.** Measured, not
> estimated. Log-based debugging for the same problem is ten minutes or more.
>
> **8 out of 9 on our labelled evaluation set.** I'm saying it that way on
> purpose — not 'eighty-nine percent'. Nine cases is a demonstration, not a
> statistical claim, and I'm not going to dress it up as one.
>
> The one miss was a case we labelled WARN and the system called ANOMALY — a
> severity disagreement on a genuinely borderline case, erring toward
> over-flagging. **We didn't relabel it to make the score look better.**
> Relabelling until the model agrees is how an evaluation stops meaning
> anything.
>
> **151 tests, 84% backend coverage**, and every experiment writes a timestamped
> JSON and CSV artifact, so any number I've said is re-plottable without
> re-running it."

---

## [4:15–5:00] Built to survive being wrong

> "Three decisions I'd defend in a code review.
>
> **One — when we fail, we say so.** If our own model is unreachable, we never
> return OK. We return a warning marked *degraded*: 'I couldn't check.' Never OK,
> because we won't claim health we didn't verify. Never ANOMALY, because our
> outage isn't the agent's fault.
>
> **Two — the evaluation refuses to lie.** If any test case failed to reach the
> model, it prints no accuracy score at all. A number computed over failed API
> calls is worse than no number. We learned that the hard way: an early
> experiment reported a 100% improvement that turned out to be entirely
> rate-limiting artifacts. We found it, we fixed the harness, and it's written
> down in our progress log.
>
> **Three — observing never blocks.** Submitting a trace returns in under a
> millisecond and judging happens on a worker thread. Watching an agent must not
> slow it down."

---

## [5:00–5:35] What we haven't done

*Say this before anyone asks. It is worth more than another feature.*

> "What we haven't built.
>
> **No auto-correction.** We detect and explain — we don't step in and fix. The
> button is on the dashboard, deliberately disabled. You can't fix what you
> can't see in time, and seeing it is the part we solved.
>
> **We built a memory layer** — every failure feeds a knowledge graph that
> abstracts to *capabilities* rather than endpoint names, because the agent
> invents a different URL every run but reaches for the same capability. Those
> lessons get injected back into the agent's prompt.
>
> **We have not proven it reduces failures.** The mechanism works and the
> lessons are correct. The effect is unmeasured. So I'm not going to claim it
> learns — I'm telling you it's built and that's our next measurement."

---

## [5:35–6:00] Close

> "AI agents are being given real jobs — real customers, real money, real
> records. And right now, when they go wrong, they go wrong **quietly**, and
> nobody finds out for ten minutes.
>
> SentinelMind is a second pair of eyes that's actually watching. Under a second,
> in plain English, while there's still time to act.
>
> Thank you."

---

# THE 3-MINUTE CUT

Drop sections **4:15–5:00** and **5:00–5:35**. Keep the limitations to one line
in the close:

> "To be clear about scope: we detect and explain, we don't auto-correct — and
> our memory layer is built but its effect is unmeasured."

Keep the demo and the loop explanation **at full length.** Those are what win.

---

# Q&A BANK

### "How is this different from LangSmith?"

> "LangSmith records; we judge. It answers *what did my agent do* after the
> fact, when you go looking. We answer *is my agent okay right now*, without
> being asked.
>
> And honestly — LangSmith is a mature product and better than us at most of
> what it does. Deep history, team features, dataset management. We're not
> replacing it. It's built for the moment after you know something's wrong.
> We're built for the moment you don't. They keep the record, we ring the bell."

### "Isn't this just LLM-as-a-judge? That's not new."

> "You're right, and we don't claim it is. Observability tools exist,
> LLM-as-a-judge is a known technique. What's ours is *where we draw the line* —
> we compute the deterministic parts ourselves and hand the model facts, rather
> than asking it everything. That's why our loop detection is reproducible
> instead of hopeful."

### "You said 'intervenes' in your tagline but you don't intervene."

> "Fair catch, and it's flagged in our own notes. Today we detect and explain.
> Intervention is the next step, and it's only *possible* because detection is
> fast enough to act on — you can't interrupt an agent on information that
> arrives ten minutes late. We didn't want to claim it before we'd built it."

### "What if the monitoring AI is wrong?"

> "It will be sometimes — it's a model. Three mitigations. Every verdict carries
> a confidence score, and there's a configurable threshold that downgrades
> low-confidence anomalies so you don't get alert fatigue. Every verdict carries
> a written explanation, so a human can overrule it in two seconds. And the
> deterministic signals — repeat counts, unregistered tools, raised
> exceptions — aren't the model's opinion at all."

### "Why Groq and not GPT-4 or Claude?"

> "Speed and cost. A verdict is a short classification, not a reasoning problem,
> so throughput matters more than frontier reasoning. Groq's LPU inference is
> what gets us a sub-second p95. The model is one environment variable — we
> could swap it in a line."

### "Does it slow down the agent it's watching?"

> "No, by design. Submitting a trace returns in under a millisecond — it queues
> and returns immediately. Judging happens on a separate worker thread. If that
> POST blocked, we'd be adding 600ms to every step of the agent we're supposed
> to be helping."

### "What happens when your API is down?"

> "Two answers. In production, we degrade to a warning marked *degraded* — the
> dashboard never goes blank and never claims false health. For a demo, we have
> an offline mode that replays recorded verdicts with no network call at all.
> We verified it by booting the server with a deliberately invalid API key and
> replaying — it reproduced the live run exactly."

### "How do you know it actually works?"

> "Two different things, and we keep them separate. 151 tests prove the plumbing
> with a fake model — they run offline in under a second with no API key. The
> evaluation proves the *judgement* with the real model, against nine labelled
> cases with written rationales. Tests catch broken code; evals catch bad
> judgement. Every eval run writes a JSON artifact, so the numbers are auditable."

### "Nine test cases is very few."

> "Agreed, and that's why I said 'eight of nine on our labelled set' rather than
> a percentage. It's enough to demonstrate the mechanism, not enough to
> generalise from. Growing it is on our list."

### "Could an agent learn to evade this?"

> "Not the deterministic parts — you can't hide from a hash by rephrasing. The
> semantic judgements are a model, so in an adversarial setting they'd be
> attackable like any model. Our threat model is agents that fail, not agents
> that attack."

### "What's next?"

> "Three things, in order. Prove the learning loop actually reduces failures —
> it's built, it's unmeasured. Then gated intervention: block a destructive step
> before it executes, not after. And open-source the decorator as a pip package,
> because the integration surface is one line and it should be."

---

# THREE RULES ON STAGE

1. **Say "8 of 9 on our labelled set."** Never a percentage.
2. **Say "JSON mode enforced by the API."** Not "strict schema" — we run the
   fallback path, and it's one curl away from being checked.
3. **Name a limitation before they find it.** It's what makes every other number
   you said believable.
