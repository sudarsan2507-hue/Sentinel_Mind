"""Your own agent, watched by SentinelMind -- the whole integration is the
@monitor lines and one connect() call.

    python backend/app.py                    # terminal 1: the server
    python examples/connect_your_agent.py    # terminal 2: this agent

Open http://127.0.0.1:5000/dashboard to watch it. A travel agent rebooking a
cancelled flight: nothing here is part of SentinelMind's own demo, which is the
point -- the tools are registered when it connects, so they are judged as real
tools. When it tries to charge the card, the dashboard asks you to approve.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import sentinel  # noqa: E402
from decorator import GuardBlocked, monitor  # noqa: E402


# -- your tools, unchanged apart from @monitor -------------------------------

@monitor(tool_name="lookup_booking")
def lookup_booking(ref: str) -> dict:
    return {"ref": ref, "flight": "BA117", "status": "cancelled", "passenger": "R. Mehta", "fare_usd": 640}


@monitor(tool_name="search_flights")
def search_flights(origin: str, dest: str, date: str) -> list[dict]:
    return [{"flight": "BA119", "departs": f"{date} 18:40", "seats": 4, "fare_usd": 640},
            {"flight": "VS4", "departs": f"{date} 20:15", "seats": 1, "fare_usd": 910}]


@monitor(tool_name="rebook", risky=True)          # changes the booking: judged before it runs
def rebook(ref: str, flight: str) -> str:
    return f"{ref} moved to {flight}"


@monitor(tool_name="charge_card", approval=True)  # takes money: a person decides
def charge_card(ref: str, amount_usd: float) -> str:
    return f"charged ${amount_usd:.2f} to the card on {ref}"


@monitor(tool_name="send_email")
def send_email(to: str, body: str) -> str:
    return f"sent to {to}"


# -- the one line that connects it --------------------------------------------

def main() -> None:
    sentinel.connect(
        "http://127.0.0.1:5000",
        goal="Rebook passenger R. Mehta (booking QX7P2) onto the next available flight "
             "after their cancellation, at no extra cost to them, and tell them the new times.",
        tools=[lookup_booking, search_flights, rebook, charge_card, send_email],
        guard=True,
        approval_timeout=30,
    )

    # -- the agent's run (scripted here; an LLM agent calls the same tools) --
    booking = lookup_booking("QX7P2")
    options = search_flights("LHR", "JFK", "2026-10-19")
    choice = options[0]
    print(rebook("QX7P2", choice["flight"]))
    try:
        # A mistake on purpose: the cancellation was the airline's, so the
        # passenger owes nothing -- yet the agent tries to charge the fare.
        print(charge_card("QX7P2", choice["fare_usd"]))
    except GuardBlocked as exc:
        print(f"SentinelMind stopped it: {exc}")
    print(send_email("r.mehta@example.com",
                     f"You're rebooked on {choice['flight']}, departing {choice['departs']}. "
                     f"No extra charge. Original booking {booking['ref']}."))
    print("\nDone. The run is on the dashboard: http://127.0.0.1:5000/dashboard")


if __name__ == "__main__":
    main()
