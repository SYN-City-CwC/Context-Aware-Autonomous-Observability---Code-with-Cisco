from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["scenario"] == "the-final"
    assert payload["ticks"] > 0


def test_scenario_hides_attack_information() -> None:
    response = client.get("/api/scenario")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"]
    serialized = str(payload)
    assert "attacks" not in payload
    assert "CS-01" not in serialized
    assert "credential" not in serialized


def test_timeline_hides_truth_by_default() -> None:
    response = client.get("/api/timeline")

    assert response.status_code == 200
    payload = response.json()
    assert "truth" not in str(payload["ticks"])
    assert "CS-01" not in str(payload["decisions"])


def test_timeline_truth_opt_in() -> None:
    response = client.get("/api/timeline?truth=1")

    assert response.status_code == 200
    payload = response.json()
    assert any(tick["truth"] for tick in payload["ticks"])


def test_websocket_replay_streams_ticks_decisions_and_end() -> None:
    with client.websocket_connect("/ws/replay") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert "attacks" not in hello["scenario"]

        websocket.send_json({"cmd": "start", "speed": 1000000})
        status = websocket.receive_json()
        assert status["type"] == "status"

        saw_tick = False
        saw_decision = False
        for _ in range(1200):
            message = websocket.receive_json()
            if message["type"] == "tick":
                saw_tick = True
                assert "truth" not in message["tick"]
                assert "CS-01" not in str(message)
                saw_decision = saw_decision or bool(message["decisions"])
            if message["type"] == "end":
                assert saw_tick
                assert saw_decision
                return
        raise AssertionError("replay did not end")
