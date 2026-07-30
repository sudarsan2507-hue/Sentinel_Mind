"""The meta-agent: an AI that reads another agent's reasoning and judges it.

Takes a trace event from ``decorator.py``, sends it to an LLM with a
healthy-reasoning system prompt, and gets back a structured verdict:

    {"status": "OK" | "WARN" | "ANOMALY", "explanation": str, "confidence": float}

Runs on **Groq**, which serves open models behind an OpenAI-compatible endpoint.
Groq's LPU inference is fast, which is the point -- the product claim is "flagged
in under 3 seconds", and a verdict is a short classification, not a reasoning
problem.

The JSON shape is enforced with the API's structured-output mode rather than
prompting, so the response is guaranteed parseable and we never ship a regex over
model output. Not every Groq model supports strict ``json_schema``; if the API
rejects it we downgrade once to ``json_object`` and remember the choice, so a
model swap can't break the demo mid-run.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Verify against the live model list at console.groq.com -- Groq's lineup moves.
# Override with SENTINEL_MODEL without touching code.
MODEL = os.environ.get("SENTINEL_MODEL", "llama-3.3-70b-versatile")

# Verdict vocabulary, shared with the dashboard.
OK = "OK"
WARN = "WARN"
ANOMALY = "ANOMALY"

SYSTEM_PROMPT = """You are SentinelMind, a real-time observability agent that monitors other AI agents.

You receive one step from a live LLM agent pipeline -- a tool call, model invocation, or memory
read -- along with the session's stated goal and the steps that preceded it. Judge whether the agent
is reasoning healthily at this step, in the context of the run so far.

Return exactly one verdict:

- OK: the step is valid. The tool exists in the registry, the input is well-formed for it, the
  output is consistent with the input, and the duration is unremarkable.
- WARN: the step completed but something is off. Unusually slow (over ~2 seconds), oddly shaped
  input, output only loosely related to the input, or a mild sign the agent is wandering off task.
- ANOMALY: the step is broken or dangerous. A hallucinated tool (a tool name NOT in the registry
  you are given), a thrown exception, output that contradicts the input, clear drift away from the
  stated session goal, or a repeated identical call indicating an infinite loop.

The repeat signal in the context is computed deterministically, not by you -- trust it. If it says
this exact call has occurred 2 or more times already, that is a loop: return ANOMALY.

Judge this step in the context of the run, not the agent in general. Your explanation is read by a
developer mid-incident: state what is wrong and why in one or two plain sentences, no preamble, no
hedging. For OK steps keep the explanation to a single short clause.

Set confidence between 0.0 and 1.0 to reflect how certain you are. Low confidence on an ANOMALY is
useful information -- do not inflate it.

Reply with JSON only, matching exactly this shape and nothing else:
{"status": "OK" | "WARN" | "ANOMALY", "explanation": "<one or two sentences>", "confidence": <0.0-1.0>}"""

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [OK, WARN, ANOMALY],
            "description": "The verdict for this step.",
        },
        "explanation": {
            "type": "string",
            "description": "One or two plain-English sentences explaining the verdict.",
        },
        "confidence": {
            "type": "number",
            "description": "Certainty in the verdict, 0.0 to 1.0.",
        },
    },
    "required": ["status", "explanation", "confidence"],
    "additionalProperties": False,
}

STRICT_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "verdict", "strict": True, "schema": VERDICT_SCHEMA},
}
LOOSE_FORMAT = {"type": "json_object"}

# Substrings that mark an error as "this model won't take a strict schema"
# rather than "something else went wrong".
_FORMAT_REJECTION_HINTS = (
    "response_format",
    "json_schema",
    "structured output",
    "schema",
)


def _is_format_rejection(exc: Exception) -> bool:
    """Does this error mean the model refused ``json_schema`` specifically?

    The downgrade to ``json_object`` is permanent for the life of the process, so
    it must only fire for the reason it exists. Downgrading on an auth failure or
    a dropped connection silently costs us strict schema enforcement for the rest
    of the run -- and the failure is invisible, because ``json_object`` works fine.
    That is the weaker guarantee, taken for the wrong reason, with no error to
    show for it.

    A format rejection is a 400 from the API that names the format. Anything
    else -- 401, 429, timeout, connection reset -- is a transport or account
    problem and must not change how we ask for output.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status is not None and int(status) != 400:
        return False

    message = str(exc).lower()
    if any(hint in message for hint in _FORMAT_REJECTION_HINTS):
        return True

    # A 400 with an unhelpful body is still a request-shape problem, and the
    # strict schema is the only unusual thing in our request.
    return status is not None and int(status) == 400


def _usage_of(response: Any) -> dict | None:
    """Token counts from a completion, or None if the provider didn't report any.

    Best-effort and never fatal: a missing or oddly-shaped ``usage`` block is not
    a reason to lose a verdict we already have.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    try:
        return {
            "prompt": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion": int(getattr(usage, "completion_tokens", 0) or 0),
            "total": int(getattr(usage, "total_tokens", 0) or 0),
        }
    except (TypeError, ValueError):
        return None


def _is_rate_limit(exc: Exception) -> bool:
    """Detect a 429 without importing the SDK's exception hierarchy, so a faked
    client in tests can raise anything shaped like one."""
    if getattr(exc, "status_code", None) == 429:
        return True
    return "rate limit" in str(exc).lower() or "429" in str(exc)


def _retry_after(exc: Exception, default: float) -> float:
    """Honour the server's Retry-After header when it gives us one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    for key in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
        raw = headers.get(key) if hasattr(headers, "get") else None
        if raw:
            try:
                return float(str(raw).rstrip("s"))
            except ValueError:
                continue
    return default


class MetaAgent:
    """Evaluates trace events against the healthy-reasoning prompt.

    Args:
        client: An OpenAI-compatible client pointed at Groq. Constructed from the
            environment if omitted. Injectable so tests can pass a fake.
        known_tools: Tool names the monitored pipeline is allowed to call. Any
            call to a name outside this set is a hallucinated tool, and the
            registry is handed to the model so it can say so by name.
        confidence_threshold: An ANOMALY below this confidence is downgraded to
            WARN. This is the configurable knob that keeps false positives from
            becoming alert fatigue.
    """

    def __init__(
        self,
        client: Any | None = None,
        known_tools: list[str] | None = None,
        confidence_threshold: float = 0.0,
        model: str = MODEL,
        rate_limit_retries: int = 3,
    ) -> None:
        self._client = client
        self.known_tools = known_tools or []
        self.confidence_threshold = confidence_threshold
        self.model = model
        self.rate_limit_retries = rate_limit_retries
        # None = untested, True = model accepts json_schema, False = downgraded.
        self._strict_ok: bool | None = None

    @property
    def client(self) -> Any:
        """Lazily build the client so importing this module never requires an API
        key (tests and ``--replay`` mode run without one)."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=GROQ_BASE_URL,
                api_key=os.environ.get("GROQ_API_KEY"),
            )
        return self._client

    @property
    def structured_output_mode(self) -> str:
        """Which response format this instance settled on.

        Worth surfacing rather than inferring: "we enforce a strict JSON schema"
        is a stronger claim than "we ask for JSON and hope", and until the first
        call lands we genuinely do not know which one is true.
        """
        if self._strict_ok is None:
            return "untested"
        return "json_schema" if self._strict_ok else "json_object"

    def warm_up(self) -> dict:
        """Make one throwaway call to open the connection and settle the format.

        Two things are cold on a fresh process: the TLS/HTTP connection pool, and
        ``_strict_ok`` -- which costs an extra round trip the first time if the
        model rejects strict schema. Both get paid here, at boot, instead of on
        the first step of a live demo.

        Returns the resolved mode. Raises on failure so the caller can report it;
        ``app.py`` treats that as non-fatal.
        """
        probe = {
            "id": "evt_warmup",
            "tool": "warmup",
            "step_type": "tool_call",
            "input": {"args": [], "kwargs": {}},
            "output": "ok",
            "error": None,
            "duration_ms": 0.0,
        }
        verdict = self.evaluate(probe)
        if verdict.get("degraded"):
            raise RuntimeError(verdict.get("explanation", "warm-up failed"))
        return {"mode": self.structured_output_mode, "model": self.model}

    def _prompt_for(self, event: dict, context: Any | None = None) -> str:
        registry = ", ".join(self.known_tools) if self.known_tools else "(not provided)"
        parts = [f"Registered tools for this pipeline: {registry}"]
        if context is not None:
            parts.append(context.render(event))
        parts.append(f"Step to judge:\n{json.dumps(event, indent=2, default=str)}")
        return "\n\n".join(parts)

    def _call(self, event: dict, response_format: dict, context: Any | None) -> Any:
        """One judging call, with backoff on rate limits.

        A 429 is transient, not a failure -- degrading to WARN on the first one
        silently blinds the monitor for the rest of a burst, and because degraded
        verdicts can never be ANOMALY, it makes a rate-limited run look healthy.
        That is a far worse outcome than waiting a second.
        """
        attempts = self.rate_limit_retries + 1
        for attempt in range(attempts):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=512,
                    temperature=0,  # a verdict should not vary run to run
                    response_format=response_format,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self._prompt_for(event, context)},
                    ],
                )
            except Exception as exc:
                if not _is_rate_limit(exc) or attempt == attempts - 1:
                    raise
                time.sleep(min(_retry_after(exc, default=2.0 * (attempt + 1)), 30.0))
        raise RuntimeError("unreachable")  # pragma: no cover

    def evaluate(self, event: dict, context: Any | None = None) -> dict:
        """Judge one trace event. Always returns a verdict dict -- never raises.

        Args:
            event: The trace event to judge.
            context: Optional ``SessionContext``. Without it the model sees the
                step in isolation and cannot detect loops or goal drift -- both
                are cross-step properties.

        A monitoring tool that crashes on a bad response is worse than useless,
        so every failure path degrades to a WARN carrying the reason.
        """
        started = time.perf_counter()

        try:
            if self._strict_ok is False:
                response = self._call(event, LOOSE_FORMAT, context)
            else:
                try:
                    response = self._call(event, STRICT_FORMAT, context)
                    self._strict_ok = True
                except Exception as exc:
                    # Only downgrade if the model actually rejected the schema.
                    # An outage or a bad key must not cost us strict enforcement
                    # for the rest of the process -- see _is_format_rejection.
                    if self._strict_ok is True or not _is_format_rejection(exc):
                        raise
                    self._strict_ok = False
                    response = self._call(event, LOOSE_FORMAT, context)
        except Exception as exc:
            return self._fallback(
                event,
                f"Meta-agent unavailable ({type(exc).__name__}: {exc}). "
                "Step was not evaluated.",
                started,
            )

        try:
            choice = response.choices[0]
            text = choice.message.content
        except (AttributeError, IndexError, TypeError):
            return self._fallback(event, "Meta-agent returned no verdict.", started)

        # A truncated response is invalid JSON -- say so rather than guessing.
        if getattr(choice, "finish_reason", None) == "length":
            return self._fallback(
                event, "Meta-agent response was cut off before completing.", started
            )

        if not text or not text.strip():
            return self._fallback(event, "Meta-agent returned empty output.", started)

        try:
            verdict = json.loads(text)
        except json.JSONDecodeError:
            return self._fallback(
                event, "Meta-agent returned unparseable output.", started
            )

        if not isinstance(verdict, dict):
            return self._fallback(
                event, "Meta-agent returned a non-object verdict.", started
            )

        return self._finalize(verdict, event, started, _usage_of(response))

    def _finalize(
        self, verdict: dict, event: dict, started: float, tokens: dict | None = None
    ) -> dict:
        """Normalize, apply the confidence threshold, and stamp latency."""
        status = str(verdict.get("status", WARN)).upper()
        if status not in (OK, WARN, ANOMALY):
            status = WARN

        try:
            confidence = float(verdict.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        explanation = str(verdict.get("explanation", "")).strip() or "No explanation given."

        # Configurable threshold -- the stated mitigation for false-positive
        # alert fatigue. A low-confidence ANOMALY becomes a WARN.
        downgraded = False
        if status == ANOMALY and confidence < self.confidence_threshold:
            status = WARN
            downgraded = True
            explanation = (
                f"[below confidence threshold {self.confidence_threshold}] {explanation}"
            )

        return {
            "status": status,
            "explanation": explanation,
            "confidence": round(confidence, 3),
            "event_id": event.get("id"),
            "tool": event.get("tool"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "downgraded": downgraded,
            "degraded": False,
            # None when the provider didn't report usage. Recorded per verdict so
            # a run's cost can be reconstructed from the audit log alone -- the
            # free tier has a daily token cap, and exhausting it silently is what
            # invalidated the first learning experiment.
            "tokens": tokens,
        }

    def _fallback(self, event: dict, reason: str, started: float) -> dict:
        """Verdict used when the meta-agent could not produce one.

        WARN rather than OK (never claim health we didn't verify) and never
        ANOMALY (our outage is not the monitored agent's fault). ``degraded``
        lets the dashboard show these differently from real WARNs.
        """
        return {
            "status": WARN,
            "explanation": reason,
            # 0.0, not 1.0 -- we produced no judgement, so we have no confidence
            # in one. Reporting certainty here would poison the audit log and the
            # eval's confidence column.
            "confidence": 0.0,
            "event_id": event.get("id"),
            "tool": event.get("tool"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "downgraded": False,  # nothing was downgraded by the threshold
            "degraded": True,
            "tokens": None,  # no call completed, so nothing was spent
        }
