from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models import ActionRecord, Decision, Timeline
from app.timeline import public_tick


DEFAULT_SPEED = 60.0


class ReplaySession:
    def __init__(self, timeline: Timeline):
        self.timeline = timeline
        self.index = 0
        self.speed = DEFAULT_SPEED
        self.running = False
        self.ended = False
        self._decisions = _decisions_by_tick(timeline.decisions)
        self._actions = _actions_by_tick(timeline.actions)
        self._pending = {item.id: item for item in timeline.actions if item.state == "NEEDS_REVIEW"}

    def handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        cmd = command.get("cmd")
        if cmd == "start":
            self.index = 0
            self.speed = float(command.get("speed", DEFAULT_SPEED))
            self.running = True
            self.ended = False
        elif cmd == "pause":
            self.running = False
        elif cmd == "resume":
            if not self.ended:
                self.running = True
        elif cmd == "speed":
            self.speed = float(command.get("value", self.speed))
        elif cmd == "restart":
            self.index = 0
            self.running = True
            self.ended = False
        elif cmd in {"approve", "reject"}:
            action = self._pending.get(str(command.get("action_id")))
            if action is not None:
                action.state = "APPROVED" if cmd == "approve" else "BLOCKED"
                action.transitions.append({"state": action.state, "ts": self.timeline.ticks[min(self.index, len(self.timeline.ticks)-1)].ts})
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "type": "status",
            "running": self.running,
            "index": self.index,
            "speed": self.speed,
            "ended": self.ended,
        }

    def next_message(self) -> dict[str, Any]:
        if self.index >= len(self.timeline.ticks):
            self.running = False
            self.ended = True
            return {"type": "end"}
        tick = self.timeline.ticks[self.index]
        self.index += 1
        hitl = [item.model_dump(mode="json") for item in self._actions.get(tick.ts.isoformat(), []) if item.state == "NEEDS_REVIEW"]
        return {
            "type": "tick",
            "tick": public_tick(tick),
            "decisions": [
                decision.model_dump(mode="json", by_alias=True)
                for decision in self._decisions.get(tick.ts.isoformat(), [])
            ],
            "actions": [action.model_dump(mode="json") for action in self._actions.get(tick.ts.isoformat(), [])],
            "hitl": hitl,
        }

    def delay_seconds(self, tick_seconds: int) -> float:
        if self.speed <= 0:
            return 0.1
        return max(tick_seconds / self.speed, 0.0)


def _decisions_by_tick(decisions: list[Decision]) -> dict[str, list[Decision]]:
    grouped: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        grouped[decision.ts.isoformat()].append(decision)
    return dict(grouped)


def _actions_by_tick(actions: list[ActionRecord]) -> dict[str, list[ActionRecord]]:
    grouped: dict[str, list[ActionRecord]] = defaultdict(list)
    for action in actions:
        grouped[action.ts.isoformat()].append(action)
    return dict(grouped)
