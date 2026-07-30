"""Accumulated failure memory, as a graph, fed back to the agent.

SentinelMind detects mistakes. This turns detection into memory: every non-OK
verdict is ingested as nodes and edges, persisted across runs, and distilled into
short lessons that can be injected into the monitored agent's system prompt.

**This is not training.** No weights change. It is retrieval-augmented prompting
over an accumulated failure store. Say it that way -- the honest description is
still a genuine closed loop, and overclaiming it invites the one question you
cannot answer.

## Why the graph abstracts to capabilities

Observed across three baseline runs of the same task, the agent invented:

    run 1:  /v1/orders/refund       /v1/orders/refund-status   /v1/notifications/send
    run 2:  /v1/orders/refund       /v1/customers/notifications
    run 3:  /v1/orders/refund       /v1/orders/notification    /v1/support/escalate

The *capability* it reaches for is stable -- refund, notification, escalation --
but the exact path is different almost every time. A graph keyed on literal tool
names would memorise strings that never recur and generalise nothing.

So endpoints are classified into capability nodes, and lessons are written about
capabilities. "You have no way to issue refunds" transfers to the next run;
"/v1/orders/refund returned 403" does not.

## Shape

    (tool)       --exhibits-->  (failure_mode)     how this call went wrong
    (tool)       --requires-->  (capability)       what it was reaching for
    (capability) --missing_in--> (goal)            the gap that caused it

Edges carry occurrence counts, so lessons can be ranked by how often a mistake
actually recurs rather than by how recent it is.
"""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "knowledge" / "graph.json"

# Failure modes we distinguish. Kept small on purpose -- a taxonomy nobody can
# hold in their head produces lessons nobody can act on.
HALLUCINATED_TOOL = "hallucinated_tool"
INFINITE_LOOP = "infinite_loop"
GOAL_DRIFT = "goal_drift"
EXCEPTION = "exception"
INEFFICIENT = "inefficient_reasoning"

# Capability keywords -> canonical capability. Matched against the tool name and
# endpoint path, longest-token-first so "refund-status" lands on refund.
CAPABILITY_PATTERNS: list[tuple[str, str]] = [
    (r"refund|reimburs|money.?back", "issue_refunds"),
    (r"notif|email|sms|message|alert", "notify_customers"),
    (r"escalat|supervisor|manager|ticket", "escalate_to_a_human"),
    (r"cancel|revoke|terminat", "cancel_orders"),
    (r"delete|remove|purge|drop", "delete_records"),
    (r"charge|payment|invoice|billing", "process_payments"),
    (r"update|modify|patch|write|create", "write_data"),
]


def classify_capability(tool_name: str) -> str:
    """Map a tool or endpoint to the capability it was reaching for."""
    haystack = tool_name.lower()
    for pattern, capability in CAPABILITY_PATTERNS:
        if re.search(pattern, haystack):
            return capability
    return "an_unrecognised_capability"


def classify_failure(event: dict, verdict: dict, known_tools: list[str]) -> str:
    """Decide how this step went wrong.

    Deterministic signals first -- an unregistered tool name and a raised
    exception are facts, not judgements. Only fall back to reading the
    meta-agent's explanation when there is no hard signal, and prefer the
    verdict's own words over guessing.
    """
    tool = event.get("tool", "")
    explanation = (verdict.get("explanation") or "").lower()

    # Fact: the tool is not in the registry.
    if tool and known_tools and tool not in known_tools:
        return HALLUCINATED_TOOL

    # The meta-agent is told to trust the deterministic repeat signal, so its
    # loop language is reliable here.
    if "loop" in explanation or "repeat" in explanation:
        return INFINITE_LOOP

    if event.get("error"):
        return EXCEPTION

    if "drift" in explanation or "goal" in explanation:
        return GOAL_DRIFT

    return INEFFICIENT


class KnowledgeGraph:
    """Persistent, count-weighted graph of how agents have failed before."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STORE
        self._lock = threading.Lock()
        # (type, id) -> {"type", "id", "count", "first_seen", "last_seen", ...}
        self._nodes: dict[tuple[str, str], dict] = {}
        # (src_key, relation, dst_key) -> count
        self._edges: dict[tuple[tuple[str, str], str, tuple[str, str]], int] = defaultdict(int)
        self._runs = 0
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt store must not stop the server. Start fresh; losing
            # accumulated memory is recoverable, refusing to boot is not.
            return
        for n in raw.get("nodes", []):
            self._nodes[(n["type"], n["id"])] = n
        for e in raw.get("edges", []):
            key = ((e["src_type"], e["src_id"]), e["relation"], (e["dst_type"], e["dst_id"]))
            self._edges[key] = e["count"]
        self._runs = raw.get("runs", 0)

    def save(self) -> None:
        with self._lock:
            payload = self._serialize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _serialize(self) -> dict:
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "runs": self._runs,
            "nodes": list(self._nodes.values()),
            "edges": [
                {
                    "src_type": src[0], "src_id": src[1],
                    "relation": rel,
                    "dst_type": dst[0], "dst_id": dst[1],
                    "count": count,
                }
                for (src, rel, dst), count in self._edges.items()
            ],
        }

    # -- mutation -----------------------------------------------------------

    def _touch(self, ntype: str, nid: str, **extra) -> tuple[str, str]:
        key = (ntype, nid)
        now = datetime.now(timezone.utc).isoformat()
        node = self._nodes.get(key)
        if node is None:
            node = {"type": ntype, "id": nid, "count": 0, "first_seen": now, **extra}
            self._nodes[key] = node
        node["count"] += 1
        node["last_seen"] = now
        node.update(extra)
        return key

    def ingest(
        self,
        event: dict,
        verdict: dict,
        known_tools: list[str],
        goal: str = "",
    ) -> dict | None:
        """Record one non-OK verdict. Returns the derived facts, or None if the
        verdict was healthy -- we only remember mistakes."""
        if verdict.get("status") == "OK":
            return None
        # A degraded verdict means we could not look, not that the agent erred.
        # Remembering it would teach a lesson about our own outage.
        if verdict.get("degraded"):
            return None

        tool = event.get("tool") or "unknown_tool"
        failure = classify_failure(event, verdict, known_tools)
        capability = classify_capability(tool)

        with self._lock:
            tool_key = self._touch("tool", tool, last_verdict=verdict.get("status"))
            failure_key = self._touch("failure_mode", failure)
            self._edges[(tool_key, "exhibits", failure_key)] += 1

            # Only hallucinated tools imply a missing capability. A loop on a
            # legitimate tool is not a capability gap.
            if failure == HALLUCINATED_TOOL:
                cap_key = self._touch("capability", capability, available=False)
                self._edges[(tool_key, "requires", cap_key)] += 1
                if goal:
                    goal_key = self._touch("goal", goal[:160])
                    self._edges[(cap_key, "missing_in", goal_key)] += 1

        return {"tool": tool, "failure_mode": failure, "capability": capability}

    def start_run(self) -> None:
        with self._lock:
            self._runs += 1

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
            self._runs = 0
        if self.path.exists():
            self.path.unlink()

    # -- reading ------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return self._serialize()

    def summary(self) -> dict:
        with self._lock:
            by_type: dict[str, int] = defaultdict(int)
            for (ntype, _), _node in self._nodes.items():
                by_type[ntype] += 1
            return {
                "runs": self._runs,
                "nodes": len(self._nodes),
                "edges": len(self._edges),
                "by_type": dict(by_type),
            }

    def _missing_capabilities(self) -> list[tuple[str, int]]:
        """Capabilities the agent has repeatedly reached for and lacked, most
        frequent first."""
        totals: dict[str, int] = defaultdict(int)
        for (src, rel, dst), count in self._edges.items():
            if rel == "requires" and dst[0] == "capability":
                totals[dst[1]] += count
        return sorted(totals.items(), key=lambda kv: -kv[1])

    def _looping_tools(self) -> list[tuple[str, int]]:
        totals: dict[str, int] = defaultdict(int)
        for (src, rel, dst), count in self._edges.items():
            if rel == "exhibits" and dst == ("failure_mode", INFINITE_LOOP):
                totals[src[1]] += count
        return sorted(totals.items(), key=lambda kv: -kv[1])

    def _invented_names(self, capability: str, limit: int = 3) -> list[str]:
        names = [
            src[1]
            for (src, rel, dst), _c in self._edges.items()
            if rel == "requires" and dst == ("capability", capability)
        ]
        return sorted(set(names))[:limit]

    def lessons(self, limit: int = 6) -> list[str]:
        """Distil the graph into short, actionable instructions.

        Written as constraints the agent can follow, not as a report. Each one
        names the count so the agent can weigh it, and says what to do *instead*
        -- a prohibition with no alternative just stalls the run.
        """
        with self._lock:
            missing = self._missing_capabilities()
            looping = self._looping_tools()
            runs = self._runs

        out: list[str] = []

        for capability, count in missing:
            readable = capability.replace("_", " ")
            examples = self._invented_names(capability)
            example_text = f" (previously tried: {', '.join(examples)})" if examples else ""
            out.append(
                f"You have NO tool that can {readable}. Across {count} previous attempt(s) "
                f"an endpoint for it was invented and failed{example_text}. Do not try again -- "
                f"state plainly in your final answer that this action requires a human."
            )

        for tool, count in looping:
            out.append(
                f"Calling '{tool}' repeatedly with the same arguments has been flagged as a "
                f"loop {count} time(s). Its output does not change between calls -- call it "
                f"once, then work with what it returned."
            )

        if runs and not out:
            out.append(
                f"No recurring failures recorded across {runs} previous run(s)."
            )

        return out[:limit]

    def lesson_block(self) -> str:
        """The lessons formatted for injection into a system prompt."""
        lessons = self.lessons()
        if not lessons:
            return ""
        numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(lessons, 1))
        return (
            "LESSONS FROM PREVIOUS RUNS (learned by the monitoring layer -- these are "
            "observed facts about your actual capabilities, not suggestions):\n"
            f"{numbered}"
        )


# Shared instance used by the server.
knowledge_graph = KnowledgeGraph()
