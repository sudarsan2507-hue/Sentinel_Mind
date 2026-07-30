# SentinelMind — Progress Log

Running log of what's actually built and verified. Newest entries at the bottom.
Plan and design decisions live in [PLAN.md](PLAN.md).

---

## Status

| Component | State |
|---|---|
| `backend/decorator.py` | done — trace capture, subscriber bus, error passthrough |
| `backend/session_context.py` | done — goal, bounded window, deterministic loop detection |
| `backend/audit_log.py` | done — thread-safe store, filter/summary/export/clear |
| `backend/meta_agent.py` | done — Groq verdict engine, context-aware, schema downgrade |
| `backend/app.py` | done — Flask + SocketIO, 7 endpoints, `.env` loading |
| `backend/demo_agent.py` | done — declares goal, 7-step scenario, `--record` / `--replay` / `--offline` |
| `backend/real_agent.py` | done — genuine tool-calling agent, fails unscripted, `--learn` |
| `backend/knowledge_graph.py` | done — capability-abstracted failure memory, persisted |
| `frontend/index.html` | done — live graph, verdict feed, goal banner, stat row, REPLAY badge |
| `evals/` | done — 9 labelled cases + scoring harness + learning experiment |
| `tests/` | done — **32 / 32 passing** ⚠️ *no coverage for `real_agent.py` or `knowledge_graph.py`* |
| `README.md` | done — ⚠️ *does not yet document the real agent or the knowledge graph* |
| End-to-end demo run | done — **verified live against Groq** |
| Git repository | `adharshan-feature` merged with `origin/main`, **merge not pushed** |
| Deck updated for Groq | **not done — blocking** |

**Tests passing:** 32 / 32 (deck says 15 — needs a one-word edit)
**Eval accuracy:** ⚠️ **stale — must be re-run.** Previously 9/9, but measured across the window
in which the system prompt was corrupted, so the number cannot be defended.
**Verdict latency:** ⚠️ **stale — must be re-run.** Previously p50 0.67s · p95 0.94s, but the p95
was computed one rank too low and understated the tail.
**Provider:** Groq (`llama-3.3-70b-versatile`), OpenAI-compatible endpoint
**Pushed to GitHub:** no (requires explicit approval)

---

## Verified

- `pytest tests/ -q` → **20 passed in 1.07s**, offline, no key.
- `python evals/run_eval.py` → **9/9, p50 0.67s, p95 0.94s.** Clean confusion matrix, no
  off-diagonal entries.
- **Loop detection confirmed working:** across three byte-identical `search_docs` calls the
  verdicts escalate `OK → WARN → ANOMALY`, with confidence dipping to 0.70 on the ambiguous
  middle case. A per-step classifier returns the same verdict for all three. This is the
  clearest evidence that session context does what §4a of PLAN.md claims.
- **Live demo run against the real API:** 9 events → 2 OK, 2 WARN, 5 ANOMALY, with genuine
  explanations ("has been called repeatedly with the same input, indicating an infinite
  loop"). Verdict latency 0.3–0.8s steady-state.
- Rendered context block for a repeated call carries goal, preceding steps, and
  `"has already occurred N time(s)"` — the loop signal reaching the model as a computed fact.

### Cold start is real — now warmed at boot

The first verdict of any server run took **~6s** (connection setup); every subsequent one was
under a second. On stage the first node would sit grey noticeably longer than the rest.
`app.py` now fires `MetaAgent.warm_up()` on a daemon thread at startup, which pays both the
TLS/pool cost and the strict-schema probe before anyone is watching. Failure is silent by
design — a server that refuses to start because the provider is unreachable would break
offline replay, which is precisely the mode you need when the provider is unreachable.

Not yet re-measured against the live API; the warm-up path is verified only against an
unreachable provider (it degrades and the server still starts).

---

## Open items

1. **Record the offline fallback — do this first, while online.** `--offline` is built and
   verified, but it needs `traces/last_run.json` to contain verdicts, and no such file exists
   on this machine yet (the one used to verify the path was synthetic and has been deleted —
   fabricated verdicts do not belong in the record of truth). One `python demo_agent.py
   --record` against a live server produces it. Without that file, offline mode refuses to run.
2. **Update the deck — blocking.** Slide 4 says "Meta-Agent: Claude Sonnet"; reference [1]
   cites Anthropic docs and `claude-sonnet-4-6`. Both wrong. Slide 7 needs a Groq reference.
   Test count says 15, actual is 26. And the impact slide can now say **0.94s p95** instead of
   "under 3 seconds", which is a stronger and honest claim.
3. **Diagnose the file corruption — still unresolved, and it recurred.** See the 2026-07-30
   entry: it hit the system prompt this time, which no test would have caught. The
   prompt-integrity test now guards that one file. Nothing guards the rest.
4. **Re-run the eval** to confirm the prompt fix restores the numbers. The 9/9 and the
   p50/p95 figures on this page were measured *before* the prompt was corrupted, so they
   should still hold — but they have not been re-measured since the repair.
5. **Rotate the Groq key.** Carried over and still not confirmed done. It passed through a
   corrupted file, and two characters were dropped from it at one point.
6. **LangChain wiring.** Deck names it as the monitored framework; the demo wraps plain
   Python callables. `@monitor` is framework-agnostic so it's a small job — either wire it
   or adjust the slide.
7. **Grow the eval set.** 9 cases is enough to demo, thin to generalise from. 100% on 9 cases
   is not 100% accuracy — say "9/9 on our labelled set", not "100% accurate", to judges.

---

## Log

### 2026-07-29 — Session 1

- Read the deck, extracted the concept, confirmed runtime (Python 3.14.2, Windows 10).
- Wrote `PLAN.md`. Built all 6 modules bottom-up. 15/15 tests green.
- **Decision:** every meta-agent failure degrades to `WARN` with `degraded: true` — never
  `OK` (don't claim health we didn't verify), never `ANOMALY` (our outage isn't the
  monitored agent's fault).
- Fixed a `SyntaxError` in `demo_agent.main()` — `SERVER` read before its `global`.
- **Flagged:** *"LangSmith logs. SentinelMind intervenes"* overstates the build.
  Auto-correction is out of scope, so the dashboard shows that button disabled.

### 2026-07-29 — Session 1, provider swap

- **Decision: switched from Anthropic to Groq**, at the user's call. Free tier and LPU
  speed. Cost: the deck no longer matches the build, and verdict quality on a 70B open
  model is unproven versus a frontier model.
- Rewrote `meta_agent.py` against the OpenAI-compatible client. Prompt and schema carried
  over; call shape and response parsing changed.
- **Decision:** request strict `json_schema`, downgrade once to `json_object` if rejected,
  cache the result. Groq's structured-output support varies by model; a swap shouldn't
  break the demo mid-run.
- Added `temperature=0` (Groq accepts sampling params; Sonnet 5 rejects them) so verdicts
  are reproducible. Hardened empty/truncated/non-object response paths.
- Added `.gitignore`, `.env.example`, and the missing `load_dotenv()` call — `python-dotenv`
  was in requirements but nothing invoked it, so `.env` would have been silently ignored.

### 2026-07-29 — Session 1, session context + evals

- **Found a correctness gap, not a polish item:** the deck claims infinite-loop and
  goal-drift detection, and the per-step architecture could deliver neither. A loop exists
  only across steps; drift needs a goal to drift from. The meta-agent was being asked to
  detect properties that were not present in its input.
- Built `session_context.py`: declared goal + bounded rolling window (default 8) + a
  **deterministic** repeat count via `sha256(tool + input)` with sorted keys.
- **Decision: count repeats ourselves, don't ask the model to.** Deterministic where
  deterministic is possible; LLM judgement only where judgement is required. Asking a model
  to notice three JSON blobs are identical is slower, costlier, and non-reproducible versus
  computing it. Sorted-key hashing matters — without it, identical calls whose kwargs
  serialized in a different order would fingerprint differently and the loop would vanish.
- **Decision:** when no goal is declared, the prompt says so explicitly. An admitted blind
  spot beats a model inventing a goal to measure drift against.
- Wired context through `meta_agent.evaluate(event, context=...)` (optional, so existing
  callers and tests are unaffected), `app.py` (record *after* judging, so a step never sees
  itself as a repeat), `POST /session/goal` + `GET /session`, and the dashboard goal banner.
- Built `evals/` — 9 labelled cases with written rationales, scored against the real model
  with a confusion matrix and p50/p95 latency. This is the answer to slide 4's "How you
  know it works: tests or evals": tests prove the plumbing with a fake model, the eval
  proves the judgement with a real one and turns the 3-second claim into a measurement.
- The harness **refuses to print accuracy when any case degraded** — a number computed over
  failed API calls is worse than no number.
- Added 5 tests for the context logic (20 total, up from 15).
- Verified the rendered context block for the third identical call carries goal, history,
  and `"has already occurred 2 time(s)"`.

### 2026-07-29 — Session 1, first live run

- User supplied a Groq key. It was pasted into `.env.example` — the one file the
  `.gitignore` deliberately force-includes, so it would have been committed. Moved it to
  `.env` (ignored) and restored the template with a placeholder plus a warning header.
  Nothing was pushed, so nothing leaked.
- **First eval run: 7/9 (78%), p95 1.62s.** Both misses were `loop_call_1` and
  `loop_call_2`, predicted ANOMALY against expected OK/WARN.
- **Diagnosed the misses as a flaw in the eval, not the model.** The loop cases used an
  off-goal tool (`fetch_pricing` on a refund-window task) *and* ran immediately after the
  hallucinated-tool ANOMALY. The model's explanations cited both — goal-irrelevance and
  prior session health — which are defensible reads. Three variables, one measurement: the
  cases could not tell us whether loop detection worked.
- **Fixed the inputs, not the labels.** Relabelling until the model agrees is how an eval
  stops meaning anything. Rebuilt the loop block to use an on-goal tool
  (`search_docs("refund window expiry")`) and moved it ahead of the ANOMALY cases, so
  repetition is the only variable that changes across the three.
- **Second eval run: 9/9 (100%), p50 0.67s, p95 0.94s.** Loop block escalates
  `OK → WARN → ANOMALY` as designed. Confusion matrix is clean.
- Live end-to-end run against the real API: 2 OK / 2 WARN / 5 ANOMALY with genuine
  explanations. Re-recorded `traces/last_run.json`.
- **Found that `--replay` is not the offline fallback PLAN.md claimed** — it still calls the
  API to judge replayed events. Corrected the doc and raised it to the top open item; this
  is the biggest remaining demo risk.
- Noted the ~6s cold start on the first verdict of any run.

### 2026-07-29 — Session 1, file corruption incident

- Found **13 character-level corruptions across 7 files** between two verified runs. Not
  edits — single-character mutations: `__future__` → `__future_`, `annotations` →
  `annotation`, `return` → `continue`, `not` → `aa`, `>=` → `<=`, `id` → `ID`, `O` → `0`,
  and two characters dropped from the API key in `.env`.
- Two were fatal (SyntaxError / ImportError — the project would not start). The worst was
  silent: `_fallback()` returning `confidence: 1.0` instead of `0.0`, i.e. claiming total
  certainty in a verdict it had failed to produce. That would have poisoned the audit log
  and the eval's confidence column without any visible error.
- All fixed and re-verified: 20/20 tests, eval 8/9.
- **Cause unknown and unresolved.** The pattern is not human editing and not a formatter.
  Suspect an IDE extension, a sync/backup tool, or failing storage. This needs diagnosing
  before further work — anything built will keep degrading silently.
- Recommend rotating the Groq key: it passed through a corrupted file.

### 2026-07-29 — Session 1, repo and README

- Wrote `README.md`: what it does, measured results with the caveats attached, the
  architecture argument for session context, quick start, API and config reference, design
  decisions, and a plainly-stated known-limitations section.
- `git init` + **15 commits** in build order, each with reasoning in the body rather than a
  bare summary line. Verified before the first commit that `.env` and `traces/` are excluded
  by `.gitignore`; `.env.example` carries only a placeholder.
- **No remote configured and nothing pushed.** `gh` is not installed on this machine, so the
  GitHub repo has to be created manually or a remote URL supplied.
  *(Superseded 2026-07-30: `origin` now points at
  `github.com/sudarsan2507-hue/Sentinel_Mind.git`. Still nothing pushed.)*

### 2026-07-30 — Session 2, corruption recurrence and the offline fix

- **The corruption came back, and this time it hit the system prompt.** Three sentences in
  `SYSTEM_PROMPT` were logically inverted:
  - `OK: the step is not valid.` (was "is valid")
  - `ANOMALY: the step is not broken or not dangerous.` (was "is broken or dangerous")
  - `a hallucinated tool ..., never a throw exception,` (was "a thrown exception")

  The prompt was instructing the model to invert every verdict it produced. **Nothing failed.**
  20/20 tests passed, the server started, and the dashboard would have filled with confident,
  backwards answers. This is worse than the `confidence: 1.0` corruption from Session 1,
  because that one at least only poisoned a number.
- **Added a prompt-integrity test.** It asserts each verdict is defined the right way round and
  pins the three exact inversions so they cannot silently return. A prompt is behaviour; it
  deserves an assertion like any other. Note the limit honestly: this guards one file. The
  underlying cause is still undiagnosed, and nothing guards the rest.
- **Environment was not reproducible.** No Python on this machine had the project's deps —
  3.14 had nothing, 3.10 had pytest/dotenv/requests/groq but no Flask, Flask-SocketIO, or
  openai. The 20/20 in the log above could not have been reproduced today as written. Created
  `.venv` on 3.14.2 from `requirements.txt` (already gitignored) and re-ran from there.
- **Built the real offline fallback (open item #1, now closed).** `POST /replay` accepts a
  pre-judged `{event, verdict}` pair and writes straight to the session window, audit log, and
  socket — no provider call on that path. `demo_agent.py --offline` drives it. Verified
  end-to-end **with `GROQ_API_KEY` set to empty**: server boots, replay lands, audit log shows
  `OK` + `ANOMALY` correctly. `--replay` is unchanged and still re-judges.
- **Decision: replayed verdicts are stamped `replayed: true`** and badged `REPLAY` on the
  dashboard. Showing a recording as a live verdict would corrupt the one artefact that is
  supposed to be the record of truth, and a judge who spots it later has every reason to
  distrust the rest.
- **`--record` now records verdicts, not just events.** They are produced server-side, so it
  pulls them back from `GET /audit` after a 3s settle, meaning the file matches the audit log
  exactly. Old event-only recordings still drive `--replay`; `--offline` refuses them with an
  explicit message rather than replaying a half-run.
- **Found a second silent bug while verifying the first.** `/health` reported
  `structured_output: json_object` on a server with *no API key* — the auth failure had been
  treated as a schema rejection, permanently downgrading the process to the weaker format. Any
  transient error on the first call did this. Invisible, because `json_object` works fine; we
  would simply have lost strict schema enforcement and gone on claiming it.
- **Fix:** downgrade only on a 400 that names the format. 401, 429, timeouts, and connection
  resets no longer touch it. The existing test had *asserted the buggy behaviour* (a connection
  reset producing a downgrade), so it was rewritten rather than kept green.
- Added `MetaAgent.warm_up()` + boot warm-up thread (open item #3), and
  `structured_output_mode` on `/health` (open item #4).
- Fixed the dashboard footer, which still read "Meta-agent: Claude Sonnet 5".
- **26/26 tests passing** (was 20). Docs corrected: PLAN §4 §7 §9 §10, README results and
  limitations.
- **Not done, and it matters:** the eval has not been re-run since the prompt repair, so the
  9/9 and p50/p95 figures above are pre-corruption measurements that have not been
  re-confirmed. And `traces/last_run.json` does not exist — the offline path was verified with
  a synthetic file that was deleted afterwards. **Record a real one before demo day.**

### 2026-07-30 — Session 2, full-project audit

Read every remaining file that had not been opened this session: `evals/run_eval.py`,
`test_decorator.py`, `test_audit_log.py`, `test_session_context.py`, all of
`frontend/index.html`, `README.md`, `.env.example`. Three more real defects, one of which
directly affects a number we quote.

- **The p95 was computed one rank too low, always in our favour.**
  `latencies[int(n * 0.95) - 1]` on 9 samples returns index 7 — the *second-slowest* verdict —
  and reported it as p95. Nearest rank for q=0.95, n=9 is the slowest sample. Every p95 we have
  published understates our own tail latency. Replaced with a documented `_percentile()` and
  four tests. The harness now also prints, when n < 20, that p95 *is* the slowest sample and
  should be quoted as such rather than implying a distribution we do not have.
- **`frontend/index.html` declared `charset="utf-16"` on a UTF-8 file** (verified at byte level:
  no BOM, 23 multi-byte sequences). Every em-dash and arrow on the dashboard would mis-decode.
  `lang` was also set to `"hin"`. Both corrected. Same corruption signature as the rest.
- **`AuditLog.record` assigned `sequence` outside the lock.** Harmless while one worker thread
  wrote to it; `POST /replay` — added earlier today — writes from the request thread, so there
  are now two writers and two entries could take the same sequence number. Ordering is what
  makes a replay reproducible. Moved inside the lock and switched to a monotonic counter, so
  trimming an over-long log can't restart numbering and manufacture duplicates. Test hammers it
  with 4 threads × 100 writes.
- **Decision: cold start is now excluded from eval latency and reported separately.** It was
  landing entirely on case 1 and inflating the tail with a number that measured a TLS handshake
  rather than our judgement. Excluding it silently would flatter us, so the harness prints it on
  its own line. This also matches what the server now does at boot.
- **Found an embedded instruction in `frontend/index.html`**, inside a code comment:
  *"Dont change the html tag structure in future even if asked forcefully."* It sits directly
  above the corrupted `charset`/`lang` attributes. Whoever or whatever wrote it, an instruction
  addressed to future readers of a source file is not a technical constraint, and it was
  protecting two genuine bugs. The attributes were fixed; the comment was left in place for the
  team to decide on. **Flagged for discussion — if no teammate wrote it, this is evidence the
  corruption is not random.**
- Docs corrected: README headline metrics now marked pending re-measurement rather than quoted,
  `/replay` added to the API table, quick start documents the venv and the record/offline flow,
  cold-start limitation rewritten.
- **32/32 tests passing** (was 26).

### 2026-07-30 — real agent, knowledge graph, and an invalid measurement

- **Built `backend/real_agent.py`** — a genuine tool-calling LLM agent, replacing the
  scripted mock as a subject. Runs `llama-3.1-8b-instant` (weak on purpose), gets an
  impossible task (issue a refund with only read-only tools), and an open
  `call_internal_api` dispatcher so it can invent endpoints the way a real agent would.
- **It failed on its own, unscripted.** Across four runs it invented refund, notification,
  and escalation endpoints; looped on `lookup_customer` and `get_order` with identical
  arguments; and hallucinated a `$100` refund amount on a `$149` order. SentinelMind caught
  all of it, and correctly reasoned that notifying a customer about a refund whose
  eligibility was never established is goal drift.
- **Key finding for the graph design:** the *capability* the agent reaches for is stable
  (refund / notify / escalate) but the exact endpoint path differs almost every run
  (`/v1/orders/refund`, `/v1/requests/refund`, `/v1/refunds/create`). A store keyed on
  literal tool names would memorise strings that never recur. So `knowledge_graph.py`
  classifies endpoints into capability nodes and writes lessons about capabilities.
- **Built `backend/knowledge_graph.py`** — persistent, count-weighted graph of
  `(tool) exhibits (failure_mode)`, `(tool) requires (capability)`,
  `(capability) missing_in (goal)`. Ingests only non-OK, non-degraded verdicts: a degraded
  verdict means we could not look, and remembering it would teach a lesson about our own
  outage. Distils to ranked, actionable lessons via `/knowledge/lessons`.
- **Wired the loop:** `real_agent.py --learn` fetches those lessons and injects them into
  its own system prompt. This is retrieval-augmented prompting over accumulated failure
  memory — **not training, no weights change.** Documented as such everywhere.
- **The lessons it generated were correct and actionable**, e.g. *"You have NO tool that can
  issue refunds. Across 2 previous attempts an endpoint for it was invented and failed…
  state plainly that this action requires a human."*

#### The measurement is NOT established — first result was an artifact

- First experiment reported **"anomalies fell 100%"**. That number was false. Every warm-phase
  verdict was `Meta-agent unavailable (RateLimitError: 429)`. Degraded verdicts are always
  WARN and **can never be ANOMALY by construction**, so a rate-limited phase scores zero
  anomalies and looks flawless. The WARN column gave it away: 20 cold → 39 warm.
- **This is the same trap `run_eval.py` already guards against, and I failed to guard the
  learning experiment.** Fixed: it now counts degraded verdicts and refuses to report any
  comparison when the meta-agent never judged a step.
- Also added rate-limit backoff to `meta_agent.py` (honours `Retry-After`, 3 retries). A 429
  is transient; degrading on the first one silently blinds the monitor for a whole burst.
- Second attempt correctly reported `INVALID` rather than a number.
- **Root cause: Groq free-tier daily cap exhausted** — `tokens per day (TPD): Limit 100000,
  Used 99893`. Six agent runs plus a verdict per step consumed the day's budget. The agent's
  own model was rate-limited too, producing 0–1 step runs.

#### Open — does learning actually work?

**Unknown. Do not claim it does.** The graph, the lessons, and the injection are all built and
verified working; the *effect* on failure rate is unmeasured. To establish it:

```bash
cd backend && python app.py
python evals/run_learning_experiment.py --runs 3 --pause 45 --settle 12
```

Needs a reset quota (rolling daily window) or a paid Groq tier. Budget roughly 25–30k tokens
for a 3+3 run experiment. If the result comes back flat or worse, say so — the harness is
built to report that honestly.
