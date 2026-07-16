from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.scenario import DEFAULT_SCENARIO_PATH, load_scenario
from app.timeline import build_timeline
from app.train import train_models


@pytest.fixture(scope="session")
def scenario():
    return load_scenario(DEFAULT_SCENARIO_PATH)


@pytest.fixture(scope="session")
def trained_meta(scenario):
    return train_models(scenario, n_estimators=80, verbose=False)


@pytest.fixture(scope="session")
def envelope_timeline(scenario, trained_meta):
    previous = os.environ.get("DETECTOR")
    os.environ["DETECTOR"] = "envelope"
    try:
        return build_timeline(scenario)
    finally:
        _restore_detector(previous)


@pytest.fixture(scope="session")
def rules_timeline(scenario):
    previous = os.environ.get("DETECTOR")
    os.environ["DETECTOR"] = "rules"
    try:
        return build_timeline(scenario)
    finally:
        _restore_detector(previous)


@pytest.fixture()
def envelope_env(trained_meta) -> Iterator[None]:
    previous = os.environ.get("DETECTOR")
    os.environ["DETECTOR"] = "envelope"
    try:
        yield
    finally:
        _restore_detector(previous)


def _restore_detector(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("DETECTOR", None)
    else:
        os.environ["DETECTOR"] = previous
