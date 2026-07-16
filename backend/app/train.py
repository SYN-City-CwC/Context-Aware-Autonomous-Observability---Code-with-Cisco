from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb

from app.features import CONTEXT_FEATURES, build_feature_frame
from app.generator import generate_history
from app.models import Scenario
from app.scenario import load_scenario


DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
QUANTILES = {"p10": 0.1, "p50": 0.5, "p90": 0.9}


def train_models(
    scenario: Scenario | None = None,
    *,
    model_dir: Path | None = None,
    n_estimators: int = 120,
    verbose: bool = True,
) -> dict[str, Any]:
    scenario_model = scenario or load_scenario()
    output_dir = model_dir or DEFAULT_MODEL_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ticks = generate_history(scenario_model)
    day_keys = sorted({tick.ts.date().isoformat() for tick in ticks})
    if len(day_keys) < 14:
        raise ValueError("training requires 14 chronological day windows")
    train_days = set(day_keys[:11])
    validation_days = set(day_keys[11:13])
    holdout_days = set(day_keys[13:])
    train_indices = [i for i, tick in enumerate(ticks) if tick.ts.date().isoformat() in train_days]
    validation_indices = [
        i for i, tick in enumerate(ticks) if tick.ts.date().isoformat() in validation_days
    ]
    meta: dict[str, Any] = {
        "scenario": scenario_model.name,
        "seed": scenario_model.seed,
        "trained_at": datetime.now(UTC).isoformat(),
        "split": {
            "train": [day_keys[0], day_keys[10]],
            "validation": [day_keys[11], day_keys[12]],
            "holdout": [day_keys[13], day_keys[-1]],
        },
        "feature_names": {},
        "context_feature_names": sorted(CONTEXT_FEATURES),
        "validation_coverage": {},
        "models": {},
    }
    if verbose:
        print(
            "Split: "
            f"train {day_keys[0]}..{day_keys[10]}, "
            f"validation {day_keys[11]}..{day_keys[12]}, "
            f"holdout {day_keys[13]}..{day_keys[-1]}"
        )

    for kpi in scenario_model.kpis:
        build = build_feature_frame(scenario_model, ticks, kpi.id, include_context=True)
        blind_build = build_feature_frame(scenario_model, ticks, kpi.id, include_context=False)
        x_train = build.frame.iloc[train_indices]
        y_train = build.target.iloc[train_indices]
        x_val = build.frame.iloc[validation_indices]
        y_val = build.target.iloc[validation_indices]
        meta["feature_names"][kpi.id] = build.feature_names
        meta["models"][kpi.id] = {}

        predictions: dict[str, Any] = {}
        for name, alpha in QUANTILES.items():
            model = _fit_quantile_model(x_train, y_train, alpha, scenario_model.seed, n_estimators)
            model_path = output_dir / f"{kpi.id}_{name}.txt"
            model.save_model(str(model_path))
            meta["models"][kpi.id][name] = model_path.name
            predictions[name] = model.predict(x_val)

        blind_model = _fit_quantile_model(
            blind_build.frame.iloc[train_indices],
            blind_build.target.iloc[train_indices],
            0.9,
            scenario_model.seed,
            n_estimators,
        )
        blind_path = output_dir / f"{kpi.id}_blind_p90.txt"
        blind_model.save_model(str(blind_path))
        meta["models"][kpi.id]["blind_p90"] = blind_path.name
        meta["models"][kpi.id]["blind_feature_names"] = blind_build.feature_names

        p10 = predictions["p10"]
        p90 = predictions["p90"]
        coverage = float(((y_val >= p10) & (y_val <= p90)).mean())
        meta["validation_coverage"][kpi.id] = round(coverage, 4)
        if verbose:
            print(f"{kpi.id}: validation coverage {coverage:.3f}")

    with (output_dir / "meta.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    return meta


def _fit_quantile_model(
    x_train: Any, y_train: Any, alpha: float, seed: int, n_estimators: int
) -> lgb.Booster:
    dataset = lgb.Dataset(x_train, label=y_train, free_raw_data=False)
    params = {
        "objective": "quantile",
        "alpha": alpha,
        "learning_rate": 0.06,
        "max_depth": 6,
        "num_leaves": 31,
        "min_child_samples": 20,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "seed": seed,
        "deterministic": True,
        "num_threads": 1,
        "force_col_wise": True,
        "verbosity": -1,
    }
    return lgb.train(
        params=params,
        train_set=dataset,
        num_boost_round=n_estimators,
    )


def main() -> None:
    train_models()


if __name__ == "__main__":
    main()
