from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.models import EventSpec, Scenario, Timeline
from app.replay import ReplaySession
from app.scenario import load_scenario
from app.timeline import build_timeline, public_tick
from app.reasoning import narrate_records


SCENARIO = load_scenario()
TIMELINE: Timeline | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global TIMELINE
    TIMELINE = build_timeline(SCENARIO)
    yield

app = FastAPI(title="SYN-City Stage 0 Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "scenario": SCENARIO.name, "ticks": len(_timeline().ticks)}


@app.get("/api/scenario")
def scenario() -> dict[str, Any]:
    return scenario_summary(SCENARIO)


@app.get("/api/timeline")
def timeline(truth: int = 0) -> dict[str, Any]:
    tick_payload = [
        tick.model_dump(mode="json") if truth == 1 else public_tick(tick)
        for tick in _timeline().ticks
    ]
    return {
        "scenario": scenario_summary(SCENARIO),
        "ticks": tick_payload,
        "decisions": [
            decision.model_dump(mode="json", by_alias=True)
            for decision in _timeline().decisions
        ],
        "actions": [action.model_dump(mode="json") for action in _timeline().actions],
    }


@app.get("/api/rca")
def rca(narrate: int = 0) -> list[dict[str, Any]]:
    records = narrate_records(_timeline().rca_records) if narrate == 1 else _timeline().rca_records
    return [record.model_dump(mode="json") for record in records]


@app.get("/api/actions")
def actions() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in _timeline().actions]


@app.get("/api/audit")
def audit() -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in _timeline().audit_log]


@app.websocket("/ws/replay")
async def replay(websocket: WebSocket) -> None:
    await websocket.accept()
    session = ReplaySession(_timeline())
    await websocket.send_json({"type": "hello", "scenario": scenario_summary(SCENARIO)})
    try:
        while True:
            if not session.running:
                command = await websocket.receive_json()
                await websocket.send_json(session.handle_command(command))
                continue

            delay = session.delay_seconds(SCENARIO.tick_seconds)
            try:
                command = await asyncio.wait_for(websocket.receive_json(), timeout=delay)
                await websocket.send_json(session.handle_command(command))
            except TimeoutError:
                message = session.next_message()
                await websocket.send_json(message)
                if message["type"] == "end":
                    return
    except WebSocketDisconnect:
        return


def scenario_summary(scenario_model: Scenario) -> dict[str, Any]:
    return {
        "name": scenario_model.name,
        "sim_start": scenario_model.sim_start.isoformat(),
        "sim_end": scenario_model.sim_end.isoformat(),
        "tick_seconds": scenario_model.tick_seconds,
        "kpis": [kpi.model_dump() for kpi in scenario_model.kpis],
        "events": [_event_summary(event) for event in scenario_model.events],
    }


def _timeline() -> Timeline:
    if TIMELINE is None:
        raise RuntimeError("timeline is not ready")
    return TIMELINE


def _event_summary(event: EventSpec) -> dict[str, Any]:
    payload = event.model_dump(mode="json", exclude_none=True)
    payload.pop("goals", None)
    return payload
