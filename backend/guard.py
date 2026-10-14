"""Guard mode: stop a bad step before it runs, and tell the agent why.

Watching is not enough when a step has side effects -- a refund that should not
have happened has still happened by the time a verdict lands. In guard mode the
``@monitor`` decorator asks the server *before* a tool runs, and the server
answers with one of:

    allow     run it
    block     don't run it; here is the reason and what to do instead
    pending   a human must approve it first (see the approval endpoints)
    halt      this run has gone wrong too often; stop and hand over

Checks, cheapest and most certain first:

1. **Rules, no model call.** A tool that is not in the registry is blocked --
   that is a fact, not an opinion. So is the third byte-identical call. Both are
   decided in microseconds and are never wrong about what they claim.
2. **The judge, before the fact, for risky tools only.** A tool marked risky
   (it moves money, deletes data) is judged *before* it runs, against the goal
   and the facts the agent has gathered so far. ANOMALY at or above the
   confidence bar blocks it. If the judge cannot be reached, a risky tool is
   blocked too: an unverified irreversible action is the thing to prevent.
3. **A circuit breaker.** Every block, and every post-hoc ANOMALY on a tool
   call, is a strike. Enough strikes and the run halts.
4. **Human approval** for the tools that should never run on a model's say-so.
5. **The right path** (``path_graph.py``). When the goal matches a known task,
   each move is checked against the correct path. A move off it is held and the
   user is asked: *Automate* (steer the agent back -- and keep steering), *Let it
   continue*, or *Stop*. In autopilot the steering happens without asking.
   Moves the failure memory has seen fail repeatedly count as known-wrong.

A block is not a crash. The reason travels back to the agent as the tool's
result, worded as an instruction, so its next step can change course. That is
the "correct it" half: SentinelMind cannot rewire the model, but it can stop
the action and tell it what to do instead.

The guard keeps its own record of the run rather than reading the judge's
session window. Judging is asynchronous and, on a rate-limited tier, lags the
agent by many seconds; a loop check that waits for the judge would let the loop
run. This record is written the moment a step is reported.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter, deque
from typing import Any

from knowledge_graph import UNRECOGNISED_CAPABILITY, classify_capability
from path_graph import DEVIATIONS, FORBIDDEN, KNOWN_WRONG, OFF_PATH, PathTracker, choose_path
from session_context import SessionContext

ALLOW, BLOCK, PENDING, HALT = "allow", "block", "pending", "halt"


class _PreflightContext:
    """What the judge sees when asked about a step that has NOT run yet.

    Duck-types ``SessionContext.render`` so ``MetaAgent.evaluate`` takes it
    unchanged. Unlike the post-hoc context it includes what earlier tools
    returned: whether a refund is allowed depends on the order date and the
    policy text the agent already looked up, not on tool names alone.
    """

    def __init__(self, goal: str, history: list[dict]) -> None:
        self.goal = goal
        self.history = history

    def render(self, event: dict) -> str:
        lines = [
            "PRE-EXECUTION CHECK. The step below has NOT run yet. It has side effects "
            "that may be irreversible. Judge whether it should be allowed to run:",
            "  ANOMALY if it contradicts the session goal, a policy or fact found in "
            "the earlier tool outputs, or what the user is entitled to;",
            "  WARN if it is unclear whether it is justified;",
            "  OK only if the earlier outputs clearly justify it.",
            "Your explanation is shown to the agent if the step is blocked: say plainly "
            "why, citing the fact or policy.",
            "",
            f"Session goal: {self.goal or '(not declared)'}",
        ]
        if self.history:
            lines.append("\nWhat the agent has done and learned so far, oldest first:")
            for i, h in enumerate(self.history, 1):
                result = f"ERROR: {h['error']}" if h.get("error") else f"returned: {h.get('output')}"
                lines.append(f"  {i}. {h['tool']}({h['input']}) {result}")
        else:
            lines.append("\nThe agent has not gathered any information yet.")
        return "\n".join(lines)


def _short(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


class Guard:
    """Decides, before a tool runs, whether it should.

    Args:
        known_tools: The registry. Anything else is blocked outright.
        meta_agent: The judge, used for risky tools only. ``None`` disables
            pre-checks (risky tools are then blocked -- fail closed).
        risky_tools: Tools judged before they run.
        approval_tools: Tools that need a human's approval.
        max_strikes: Blocks plus post-hoc tool-call anomalies before the run halts.
        min_confidence: An ANOMALY below this confidence warns instead of blocking.
    """

    def __init__(
        self,
        known_tools: list[str],
        meta_agent: Any = None,
        risky_tools: set[str] | None = None,
        approval_tools: set[str] | None = None,
        max_strikes: int = 4,
        min_confidence: float = 0.6,
        repeat_limit: int = 2,
        history: int = 12,
        memory: Any = None,
        learned_store: Any = None,
        path_timeout_action: str = "automate",
        paths_dir: Any = None,
    ) -> None:
        self.known_tools = set(known_tools)
        self.meta_agent = meta_agent
        self.risky_tools = set(risky_tools or ())
        self.approval_tools = set(approval_tools or ())
        self.max_strikes = max_strikes
        self.min_confidence = min_confidence
        self.repeat_limit = repeat_limit
        self._history_size = history
        # Failure memory (KnowledgeGraph): moves that failed before count as known-wrong.
        self.memory = memory
        # Where human-approved path additions are kept (a JSON file, local state).
        self.learned_store = learned_store
        # What an unanswered off-path question becomes. "automate": steering is the
        # safe default for an unattended run; letting it carry on is not.
        self.path_timeout_action = path_timeout_action
        self.paths_dir = paths_dir
        self.proposals: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.goal = ""
        self.path: PathTracker | None = None
        self.reset()

    # -- run state ----------------------------------------------------------

    def reset(self, goal: str | None = None) -> None:
        """A new run: clear history, strikes, halt state and pending approvals."""
        with self._lock:
            if goal is not None:
                self.goal = goal
            self._attempts: Counter[str] = Counter()
            self._history: deque[dict] = deque(maxlen=self._history_size)
            self.strikes = 0
            self.halted = False
            self.halt_reason = ""
            self.blocked: list[dict] = []
            self.approvals: dict[str, dict] = {}
            graph = choose_path(self.goal, self._learned(), **({"directory": self.paths_dir} if self.paths_dir else {})) if self.goal else None
            self.path = PathTracker(graph) if graph else None

    def state(self) -> dict:
        with self._lock:
            return {
                "goal": self.goal,
                "strikes": self.strikes,
                "max_strikes": self.max_strikes,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
                "blocked": len(self.blocked),
                "risky_tools": sorted(self.risky_tools),
                "approval_tools": sorted(self.approval_tools),
                "pending_approvals": [
                    {"id": k, **{f: v.get(f) for f in ("tool", "input", "created", "kind", "finding", "expected")}}
                    for k, v in self.approvals.items() if v["status"] == "pending"
                ],
                "path": self.path.graph.id if self.path else None,
                "automate": bool(self.path and self.path.automate),
            }

    def observe(self, event: dict) -> None:
        """Record a step the moment it is reported -- outputs included.

        Called from ``/trace`` before the event is queued for judging, so the
        next pre-check sees it even while the judge is still catching up.
        Blocked attempts are recorded by ``check`` itself and skipped here.
        """
        if (event.get("guard") or {}).get("action") in (BLOCK, HALT):
            return
        if event.get("step_type") == "model_call":
            return
        if self.path:
            self.path.observe(event)
        with self._lock:
            self._history.append({
                "tool": event.get("tool"),
                "input": _short((event.get("input") or {}).get("kwargs") or (event.get("input") or {}).get("args"), 160),
                "output": _short(event.get("output")),
                "error": event.get("error"),
            })

    def note_verdict(self, event: dict, verdict: dict) -> dict | None:
        """Count a post-hoc ANOMALY on a tool call as a strike.

        Model calls are excluded: a planning step that *proposes* a bad action
        is already caught when the action itself is checked, and counting both
        would halt a run for one mistake. Returns halt info if this tripped it.
        """
        if verdict.get("status") != "ANOMALY" or verdict.get("degraded") or verdict.get("blocked"):
            return None
        if event.get("step_type") == "model_call":
            return None
        return self._strike(f"{event.get('tool')}: {verdict.get('explanation', '')}")

    def _strike(self, why: str) -> dict | None:
        with self._lock:
            self.strikes += 1
            if self.halted or self.strikes < self.max_strikes:
                return None
            self.halted = True
            self.halt_reason = (
                f"SentinelMind stopped this run after {self.strikes} serious problems "
                f"(latest: {why[:200]}). Stop now: give the user an honest summary of what "
                f"you could and could not do, and say a human will follow up."
            )
            return {"halted": True, "reason": self.halt_reason, "strikes": self.strikes}

    # -- the check ----------------------------------------------------------

    def check(self, call: dict) -> dict:
        """Decide whether ``call`` (tool, input, step_type, risky?, approval?) may run."""
        tool = call.get("tool", "")
        if self.halted:
            return {"action": HALT, "rule": "circuit_breaker", "reason": self.halt_reason}
        if call.get("step_type") == "model_call":
            return {"action": ALLOW}

        if tool not in self.known_tools:
            return self._block(call, "unregistered", self._unregistered_advice(tool))

        fp = SessionContext.fingerprint(call)
        with self._lock:
            seen = self._attempts[fp]
        if seen >= self.repeat_limit:
            return self._block(
                call, "repeat",
                f"Blocked by SentinelMind: repeat call. You already called {tool} with exactly "
                f"this input {seen} times and got the same result. Use the result you already "
                f"have, or give your final answer.",
            )

        if self.path:
            decision = self._check_path(call)
            if decision is not None:
                return decision

        if tool in self.approval_tools or call.get("approval"):
            return self._request_approval(call)

        if tool in self.risky_tools or call.get("risky"):
            verdict = self._preflight(call)
            if verdict is not None:
                return verdict

        with self._lock:
            self._attempts[fp] += 1
        return {"action": ALLOW}

    def _preflight(self, call: dict) -> dict | None:
        """Judge a risky call before it runs. Returns a block, or None to allow."""
        if self.meta_agent is None:
            return self._block(call, "unverified", "Blocked by SentinelMind: this action has side "
                               "effects and could not be checked before running. Do not retry it; "
                               "tell the user a human will review the request.")
        with self._lock:
            ctx = _PreflightContext(self.goal, list(self._history))
        verdict = self.meta_agent.evaluate({**call, "output": None, "error": None, "duration_ms": 0}, context=ctx)
        if verdict.get("degraded"):
            return self._block(call, "unverified", "Blocked by SentinelMind: this action has side "
                               "effects and the safety check could not run. Do not retry it; tell "
                               "the user a human will review the request.", verdict=verdict)
        if verdict.get("status") == "ANOMALY" and float(verdict.get("confidence", 0)) >= self.min_confidence:
            return self._block(
                call, "judge",
                f"Blocked by SentinelMind before it ran: {verdict.get('explanation', '').strip()} "
                f"Do not retry this action or look for another way to do it. Explain the situation "
                f"to the user honestly and offer a human review.",
                verdict=verdict,
            )
        # Allowed. The pre-check verdict is passed back so the step is not judged twice.
        with self._lock:
            self._attempts[SessionContext.fingerprint(call)] += 1
        return {"action": ALLOW, "rule": "judge", "verdict": verdict}

    # -- the right path ------------------------------------------------------

    def _known_failures(self, tool: str) -> int:
        if self.memory is None or not hasattr(self.memory, "failures_for"):
            return 0
        return sum(self.memory.failures_for(tool).values())

    def _check_path(self, call: dict) -> dict | None:
        """None = no objection from the path. Otherwise a steer, or a question for the user."""
        tool = call.get("tool", "")
        finding = self.path.classify(tool)
        if finding["kind"] == OFF_PATH:
            failures = self._known_failures(tool)
            if failures < 2:
                return None  # unknown, not known-wrong: let it run, it shows as a detour
            finding = {**finding, "kind": KNOWN_WRONG,
                       "why": f"{tool} is not on the path and has failed {failures} times in earlier runs"}
        if finding["kind"] not in DEVIATIONS:
            return None
        if self.path.automate:
            return self._steer(call, finding)
        approval_id = f"dev_{uuid.uuid4().hex[:10]}"
        with self._lock:
            self.approvals[approval_id] = {
                "kind": "deviation", "tool": tool, "input": call.get("input"), "call": call,
                "finding": finding, "expected": [n["label"] for n in self.path.next_steps()],
                "status": "pending", "created": time.time(),
            }
        self.path.note(tool, "held", finding.get("node"))
        return {"action": PENDING, "rule": "path", "approval_id": approval_id, "kind": "deviation",
                "finding": finding, "reason": f"{tool} is off the correct path: {finding['why']}."}

    def _steer(self, call: dict, finding: dict) -> dict:
        self.path.note(call.get("tool", ""), "steered", finding.get("node"))
        # Steering a harmless detour is not a strike; a forbidden or known-wrong move is.
        return self._block(call, "path", self.path.instruction(finding),
                           strike=finding["kind"] in (FORBIDDEN, KNOWN_WRONG))

    def set_automate(self, on: bool) -> bool:
        if not self.path:
            return False
        self.path.automate = on
        return True

    def path_state(self) -> dict | None:
        if not self.path:
            return None
        return {**self.path.snapshot(), "proposals": self.list_proposals()}

    def _propose(self, call: dict) -> None:
        """The user let an off-path move continue: offer it as a new path step."""
        if not self.path:
            return
        tool = call.get("tool", "")
        key = f"{self.path.graph.id}:{tool}"
        with self._lock:
            entry = self.proposals.setdefault(key, {
                "id": f"prop_{uuid.uuid4().hex[:8]}", "path": self.path.graph.id, "tool": tool,
                "count": 0, "status": "open"})
            entry["count"] += 1

    def list_proposals(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self.proposals.values() if v["status"] == "open"]

    def resolve_proposal(self, proposal_id: str, accept: bool) -> dict | None:
        with self._lock:
            entry = next((v for v in self.proposals.values() if v["id"] == proposal_id), None)
            if not entry or entry["status"] != "open":
                return None
            entry["status"] = "accepted" if accept else "rejected"
        if accept:
            learned = self._learned()
            nodes = learned.setdefault(entry["path"], [])
            if not any(entry["tool"] in n.get("tools", []) for n in nodes):
                nodes.append({"id": f"learned_{entry['tool']}", "label": f"{entry['tool']} (approved in a run)",
                              "tools": [entry["tool"]], "requires": [], "optional": True, "max_visits": 2})
            self._save_learned(learned)
            if self.path and self.path.graph.id == entry["path"]:
                keep = self.path
                graph = choose_path(self.goal, learned, **({"directory": self.paths_dir} if self.paths_dir else {}))
                if graph:
                    keep.graph = graph
        return dict(entry)

    def _learned(self) -> dict:
        if not self.learned_store:
            return getattr(self, "_learned_mem", {})
        try:
            return json.loads(self.learned_store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_learned(self, learned: dict) -> None:
        if not self.learned_store:
            self._learned_mem = learned
            return
        try:
            self.learned_store.parent.mkdir(parents=True, exist_ok=True)
            self.learned_store.write_text(json.dumps(learned, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _block(self, call: dict, rule: str, reason: str, verdict: dict | None = None, strike: bool = True) -> dict:
        fp = SessionContext.fingerprint(call)
        with self._lock:
            self._attempts[fp] += 1
            self.blocked.append({"tool": call.get("tool"), "rule": rule, "reason": reason, "at": time.time()})
        halt = self._strike(f"{call.get('tool')} blocked ({rule})") if strike else None
        result = {"action": BLOCK, "rule": rule, "reason": reason}
        if verdict is not None:
            result["verdict"] = verdict
        if halt:
            result["halted"] = True
        return result

    @staticmethod
    def _unregistered_advice(tool: str) -> str:
        capability = classify_capability(tool)
        if capability != UNRECOGNISED_CAPABILITY:
            readable = capability.replace("_", " ")
            return (
                f"Blocked by SentinelMind: '{tool}' is not one of your tools, so you have no way "
                f"to {readable}. Do not invent another endpoint for it. Tell the user plainly "
                f"that this needs a human."
            )
        return (
            f"Blocked by SentinelMind: '{tool}' is not one of your tools. Use only the tools "
            f"you were given; if none of them can do this, say so in your answer."
        )

    # -- human approval -----------------------------------------------------

    def _request_approval(self, call: dict) -> dict:
        approval_id = f"apr_{uuid.uuid4().hex[:10]}"
        with self._lock:
            self.approvals[approval_id] = {
                "tool": call.get("tool"),
                "input": call.get("input"),
                "call": call,
                "status": "pending",
                "created": time.time(),
            }
        return {"action": PENDING, "rule": "approval", "approval_id": approval_id,
                "reason": f"{call.get('tool')} needs a human's approval before it runs."}

    def approval_status(self, approval_id: str) -> str | None:
        with self._lock:
            entry = self.approvals.get(approval_id)
            return entry["status"] if entry else None

    def decide_deviation(self, approval_id: str, choice: str) -> dict | None:
        """The user's answer to "the agent left the path": automate, continue or stop."""
        with self._lock:
            entry = self.approvals.get(approval_id)
            if not entry or entry.get("kind") != "deviation" or entry["status"] != "pending":
                return None
            entry["status"] = {"automate": "automated", "continue": "continued", "stop": "stopped"}[choice]
            call, finding = entry["call"], entry["finding"]
        if choice == "automate":
            self.path.automate = True
            return {**self._steer(call, finding), "approval_id": approval_id}
        if choice == "continue":
            if finding["kind"] != FORBIDDEN:
                self._propose(call)
            with self._lock:
                self._attempts[SessionContext.fingerprint(call)] += 1
            return {"action": ALLOW, "rule": "path_override", "approval_id": approval_id}
        with self._lock:
            self.halted = True
            self.halt_reason = ("The user stopped this run. Stop now: tell the customer honestly what "
                                "was and wasn't done, and that a person will follow up.")
        return {"action": HALT, "rule": "user_stop", "reason": self.halt_reason, "approval_id": approval_id}

    def decide(self, approval_id: str, approve: bool) -> dict | None:
        """Record a human decision. Returns the outcome, or None if unknown/already decided."""
        with self._lock:
            entry = self.approvals.get(approval_id)
            if not entry or entry["status"] != "pending":
                return None
            entry["status"] = "approved" if approve else "denied"
            call = entry["call"]
            if approve:
                self._attempts[SessionContext.fingerprint(call)] += 1
        if approve:
            return {"action": ALLOW, "rule": "approval", "approval_id": approval_id}
        return {**self._block(call, "approval_denied",
                              f"Blocked by SentinelMind: a human reviewer did not approve "
                              f"{call.get('tool')}. Do not retry it. Tell the user it was not done "
                              f"and that a person will follow up."),
                "approval_id": approval_id}

    def expire(self, approval_id: str) -> dict | None:
        """No decision in time. An approval becomes a no; a path question takes the
        configured default (steer, unless set otherwise)."""
        entry = self.approvals.get(approval_id)
        if entry and entry.get("kind") == "deviation":
            return self.decide_deviation(approval_id, self.path_timeout_action)
        return self.decide(approval_id, approve=False)
