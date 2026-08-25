from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class SignalOutcomeRecord:
    signal_name: str
    signal_score: float
    forward_return_r: float
    max_adverse_r: float
    max_favorable_r: float


@dataclass(frozen=True)
class SignalResearchSummary:
    signal_name: str
    sample_size: int
    avg_forward_return_r: float
    win_rate: float
    avg_mae_r: float
    avg_mfe_r: float
    useful: bool


class MicrostructureSignalEvaluator:
    @staticmethod
    def evaluate(records: Iterable[SignalOutcomeRecord], min_sample: int = 50, min_avg_return_r: float = 0.05) -> SignalResearchSummary:
        recs = list(records)
        if not recs:
            return SignalResearchSummary("UNKNOWN", 0, 0.0, 0.0, 0.0, 0.0, False)
        name = recs[0].signal_name
        avg_ret = mean(r.forward_return_r for r in recs)
        win_rate = sum(1 for r in recs if r.forward_return_r > 0) / len(recs)
        avg_mae = mean(r.max_adverse_r for r in recs)
        avg_mfe = mean(r.max_favorable_r for r in recs)
        useful = len(recs) >= min_sample and avg_ret >= min_avg_return_r
        return SignalResearchSummary(name, len(recs), avg_ret, win_rate, avg_mae, avg_mfe, useful)
