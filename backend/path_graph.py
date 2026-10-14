"""The right path: what a correct run of a known task looks like.

The failure memory (knowledge_graph.py) knows which moves went wrong. This knows
which moves are right, so SentinelMind can do more than say no: it can say
"not that -- this", and, with the user's go-ahead, keep the agent on course.

A path is a set of steps with preconditions, not a fixed sequence:

    get_order        requires nothing
    check_policy     requires nothing
    refund           requires get_order + check_policy, and only if refund_eligible
    tell_customer    requires get_order + check_policy

Harmless reordering (policy before order, or after) stays on the path. A
condition such as ``refund_eligible`` is evaluated on facts the agent has
actually seen -- ``days_since_purchase`` from ``get_order``'s output -- in
plain Python, so "this refund breaks the policy" is arithmetic, not a model's
opinion.

Every proposed call is classified:

    on_path        a step whose preconditions hold
    premature      a real step, but something it depends on hasn't happened
    forbidden      a real step whose condition is false (a refund out of window)
    done_already   the step is done; doing it again is circling
    off_path       a tool the path doesn't mention

Paths live in ``backend/paths/*.json`` and are chosen by matching the session
goal. Steps a human approved during runs can be added on top (see
``learned_nodes``) -- the path grows from experience, but only with a person's
say-so, because one bad approval would otherwise teach a bad path.
"""

from __future__ import annotations

import json
import operator
import threading
from collections import Counter
from pathlib import Path
from typing import Any

PATHS_DIR = Path(__file__).resolve().parent / "paths"

ON_PATH, PREMATURE, FORBIDDEN, DONE_ALREADY, OFF_PATH, KNOWN_WRONG = (
    "on_path", "premature", "forbidden", "done_already", "off_path", "known_wrong",
)
# Kinds that mean "this is not the right move here".
DEVIATIONS = {PREMATURE, FORBIDDEN, DONE_ALREADY, KNOWN_WRONG}

_OPS = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt,
        "==": operator.eq, "!=": operator.ne}


class PathGraph:
    """One task's right path, loaded from JSON."""

    def __init__(self, spec: dict, learned_nodes: list[dict] | None = None) -> None:
        self.spec = spec
        self.id = spec["id"]
        self.title = spec.get("title", self.id)
        self.facts = spec.get("facts", {})
        self.conditions = spec.get("conditions", {})
        self.nodes: list[dict] = [dict(n) for n in spec["nodes"]] + [dict(n, learned=True) for n in (learned_nodes or [])]
        self.by_id = {n["id"]: n for n in self.nodes}
        self.by_tool: dict[str, list[dict]] = {}
        for node in self.nodes:
            for tool in node.get("tools", []):
                self.by_tool.setdefault(tool, []).append(node)

    @classmethod
    def load(cls, path: Path, learned_nodes: list[dict] | None = None) -> "PathGraph":
        return cls(json.loads(path.read_text(encoding="utf-8")), learned_nodes)

    @staticmethod
    def available(directory: Path = PATHS_DIR) -> list[Path]:
        return sorted(directory.glob("*.json")) if directory.exists() else []

    def applies(self, goal: str) -> bool:
        goal = (goal or "").lower()
        return any(word in goal for word in self.spec.get("applies_when", []))

    def edges(self) -> list[tuple[str, str]]:
        return [(req, n["id"]) for n in self.nodes for req in n.get("requires", [])]

    def describe(self) -> dict:
        return {
            "id": self.id, "title": self.title, "description": self.spec.get("description", ""),
            "nodes": [{k: n.get(k) for k in ("id", "label", "tools", "requires", "when", "optional", "learned")}
                      for n in self.nodes],
            "edges": self.edges(),
        }


class PathTracker:
    """Where one run is on its path: steps done, facts seen, the route taken."""

    def __init__(self, graph: PathGraph) -> None:
        self.graph = graph
        self._lock = threading.Lock()
        self.visits: Counter[str] = Counter()
        self.facts: dict[str, Any] = {}
        self.route: list[dict] = []
        self.automate = False

    # -- what happened ------------------------------------------------------

    def observe(self, event: dict) -> None:
        """A step ran. Record its facts, and the path step it completed (if any)."""
        tool = event.get("tool")
        if event.get("step_type") == "model_call" or not tool:
            return
        failed = bool(event.get("error"))
        output = event.get("output")
        with self._lock:
            if not failed and isinstance(output, dict):
                for name, src in self.graph.facts.items():
                    if src.get("tool") == tool and src.get("field") in output:
                        self.facts[name] = output[src["field"]]
            node = None if failed else self._node_for(tool)
            if node is not None:
                self.visits[node["id"]] += 1
            self.route.append({"tool": tool, "node": node["id"] if node else None,
                               "kind": "failed" if failed else (ON_PATH if node else OFF_PATH)})

    def note(self, tool: str, kind: str, node: str | None = None) -> None:
        """A step that was stopped, steered or held -- part of the route too."""
        with self._lock:
            self.route.append({"tool": tool, "node": node, "kind": kind})

    def _node_for(self, tool: str) -> dict | None:
        nodes = self.graph.by_tool.get(tool) or []
        for node in nodes:
            if all(self.visits[r] for r in node.get("requires", [])):
                return node
        return nodes[0] if nodes else None

    # -- conditions ---------------------------------------------------------

    def condition(self, name: str) -> tuple[bool | None, str]:
        """(holds?, explanation if not). None means the facts aren't known yet."""
        spec = self.graph.conditions.get(name)
        if not spec:
            return True, ""
        value = self.facts.get(spec["fact"])
        if value is None:
            return None, f"{spec['fact'].replace('_', ' ')} is not known yet"
        try:
            holds = _OPS[spec["op"]](float(value), float(spec["value"]))
        except (KeyError, TypeError, ValueError):
            return None, f"could not evaluate {name}"
        explanation = "" if holds else spec.get("explain_false", f"{name} is false").format(**self.facts)
        return holds, explanation

    # -- the decision -------------------------------------------------------

    def classify(self, tool: str) -> dict:
        """How does calling ``tool`` now relate to the right path?"""
        nodes = self.graph.by_tool.get(tool)
        if not nodes:
            return {"kind": OFF_PATH, "node": None, "why": f"{tool} is not part of the expected path"}
        with self._lock:
            findings = [self._judge_node(node) for node in nodes]
        for wanted in (ON_PATH, FORBIDDEN, PREMATURE, DONE_ALREADY):
            for f in findings:
                if f["kind"] == wanted:
                    return f
        return findings[0]

    def _judge_node(self, node: dict) -> dict:
        base = {"node": node["id"], "label": node["label"]}
        missing = [r for r in node.get("requires", []) if not self.visits[r]]
        if missing:
            labels = ", ".join(self.graph.by_id[r]["label"].lower() for r in missing if r in self.graph.by_id)
            return {**base, "kind": PREMATURE, "why": f"{node['label'].lower()} comes after: {labels}"}
        if node.get("when"):
            holds, why = self.condition(node["when"])
            if holds is False:
                return {**base, "kind": FORBIDDEN, "why": why}
            if holds is None:
                return {**base, "kind": PREMATURE, "why": why}
        if self.visits[node["id"]] >= node.get("max_visits", 99):
            return {**base, "kind": DONE_ALREADY,
                    "why": node.get("done_hint") or f"{node['label'].lower()} is already done"}
        return {**base, "kind": ON_PATH, "why": ""}

    def next_steps(self) -> list[dict]:
        """Required steps that can be done now, in path order."""
        with self._lock:
            out = []
            for node in self.graph.nodes:
                if node.get("optional") or self.visits[node["id"]]:
                    continue
                if not all(self.visits[r] for r in node.get("requires", [])):
                    continue
                if node.get("when") and self.condition(node["when"])[0] is not True:
                    continue
                out.append(node)
            return out

    def optional_steps(self) -> list[dict]:
        with self._lock:
            return [n for n in self.graph.nodes if n.get("optional") and not self.visits[n["id"]]
                    and all(self.visits[r] for r in n.get("requires", []))]

    def finished(self) -> bool:
        """Every required step is done or ruled out by its condition."""
        with self._lock:
            for node in self.graph.nodes:
                if node.get("optional") or self.visits[node["id"]]:
                    continue
                if node.get("when") and self.condition(node["when"])[0] is False:
                    continue
                return False
            return True

    def allowed_tools(self) -> list[str]:
        """What the agent should be offered next, in autopilot. Empty = just answer."""
        if self.finished():
            return []
        tools = [t for n in self.next_steps() + self.optional_steps() for t in n.get("tools", [])]
        return list(dict.fromkeys(tools))

    def instruction(self, finding: dict) -> str:
        """The steering message for a deviation: what's wrong, what to do instead."""
        upcoming = self.next_steps()
        if self.finished():
            nxt = ("You have done everything this task needs. Give your final answer to the "
                   "customer now, honestly, and do not call any more tools.")
        elif upcoming:
            step = upcoming[0]
            nxt = f"Next correct step: {step['label'].lower()} -- {step.get('hint', 'call ' + step['tools'][0])}."
        else:
            nxt = "Wait for the information you need, then answer."
        return f"SentinelMind kept you on the correct path: not this step -- {finding['why']}. {nxt}"

    def snapshot(self) -> dict:
        with self._lock:
            visits = dict(self.visits)
            facts = dict(self.facts)
            route = list(self.route)
        return {
            "path": self.graph.describe(),
            "visits": visits,
            "facts": facts,
            "route": route,
            "next": [n["id"] for n in self.next_steps()],
            "ruled_out": {n["id"]: self.condition(n["when"])[1] for n in self.graph.nodes
                          if n.get("when") and self.condition(n["when"])[0] is False},
            "finished": self.finished(),
            "automate": self.automate,
            "allowed_tools": self.allowed_tools(),
        }


def choose_path(goal: str, learned: dict[str, list[dict]] | None = None,
                directory: Path = PATHS_DIR) -> PathGraph | None:
    """The first path whose keywords match the goal, with any learned steps added."""
    for file in PathGraph.available(directory):
        spec = json.loads(file.read_text(encoding="utf-8"))
        graph = PathGraph(spec, (learned or {}).get(spec["id"]))
        if graph.applies(goal):
            return graph
    return None
