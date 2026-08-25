from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class ForecastRecord:
    model_name: str
    timestamp: str
    target_name: str
    predicted_mean: float
    predicted_lower: float
    predicted_upper: float
    actual: float
    baseline_prediction: float


@dataclass(frozen=True)
class ForecastEvaluation:
    model_name: str
    sample_size: int
    mae: float
    rmse: float
    interval_coverage: float
    baseline_mae: float
    mae_improvement: float


class ForecastResearchEvaluator:
    @staticmethod
    def evaluate(records: Iterable[ForecastRecord]) -> ForecastEvaluation:
        recs = list(records)
        if not recs:
            return ForecastEvaluation("UNKNOWN", 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        model = recs[0].model_name
        abs_err = [abs(r.actual - r.predicted_mean) for r in recs]
        sq_err = [(r.actual - r.predicted_mean) ** 2 for r in recs]
        base_abs = [abs(r.actual - r.baseline_prediction) for r in recs]
        coverage = [1.0 if r.predicted_lower <= r.actual <= r.predicted_upper else 0.0 for r in recs]
        mae = mean(abs_err)
        baseline_mae = mean(base_abs)
        improvement = baseline_mae - mae
        return ForecastEvaluation(model, len(recs), mae, sqrt(mean(sq_err)), mean(coverage), baseline_mae, improvement)
