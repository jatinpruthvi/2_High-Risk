from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PerformanceSummary:
    trades: int
    wins: int
    losses: int
    win_rate: float
    average_win: float
    average_loss: float
    expectancy: float
    profit_factor: float
    net_pnl: float
    max_drawdown: float


def summarize_pnl(net_pnls: Iterable[float]) -> PerformanceSummary:
    values = list(net_pnls)
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    total_win = sum(wins)
    total_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    trades = len(values)
    win_rate = len(wins) / trades if trades else 0.0
    avg_win = total_win / len(wins) if wins else 0.0
    avg_loss = -total_loss / len(losses) if losses else 0.0
    expectancy = sum(values) / trades if trades else 0.0
    profit_factor = total_win / total_loss if total_loss else (float("inf") if total_win > 0 else 0.0)
    return PerformanceSummary(trades, len(wins), len(losses), win_rate, avg_win, avg_loss, expectancy, profit_factor, sum(values), max_dd)
