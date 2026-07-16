from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


_CLIENT: TestClient | None = None


def make_client(envelope_env) -> TestClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    import app.main as main

    importlib.reload(main)
    _CLIENT = TestClient(main.app)
    return _CLIENT


def test_health(envelope_env) -> None:
    client = make_client(envelope_env)
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["scenario"] == "the-final"
    assert payload["ticks"] > 0


def test_scenario_hides_attack_information(envelope_env) -> None:
    client = make_client(envelope_env)
    response = client.get("/api/scenario")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"]
    serialized = str(payload)
    assert "attacks" not in payload
    assert "CS-01" not in serialized
    assert "credential" not in serialized


def test_timeline_hides_truth_by_default_and_includes_envelope(envelope_env) -> None:
    client = make_client(envelope_env)
    response = client.get("/api/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert "truth" not in str(payload["ticks"])
    assert "CS-01" not in str(payload["decisions"])
    assert any("envelope" in tick for tick in payload["ticks"])


def test_timeline_truth_opt_in(envelope_env) -> None:
    client = make_client(envelope_env)
    response = client.get("/api/timeline?truth=1")

    assert response.status_code == 200
    payload = response.json()
    assert any(tick["truth"] for tick in payload["ticks"])


def test_websocket_replay_streams_ticks_decisions_envelope_and_end(envelope_env) -> None:
    client = make_client(envelope_env)
    with client.websocket_connect("/ws/replay") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert "attacks" not in hello["scenario"]

        websocket.send_json({"cmd": "start", "speed": 1000000})
        status = websocket.receive_json()
        assert status["type"] == "status"

        saw_tick = False
        saw_decision = False
        saw_envelope = False
        for _ in range(1200):
            message = websocket.receive_json()
            if message["type"] == "tick":
                saw_tick = True
                saw_envelope = saw_envelope or "envelope" in message["tick"]
                assert "truth" not in message["tick"]
                assert "CS-01" not in str(message)
                saw_decision = saw_decision or bool(message["decisions"])
            if message["type"] == "end":
                assert saw_tick
                assert saw_decision
                assert saw_envelope
                return
        raise AssertionError("replay did not end")
