from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Iterable

from .analytics import summarize_pnl


class DryRunReportGenerator:
    def __init__(self, mtil_path: str | Path):
        self.mtil_path = Path(mtil_path)

    def load_net_pnls(self) -> list[float]:
        if not self.mtil_path.exists():
            return []
        with self.mtil_path.open("r", encoding="utf-8", newline="") as f:
            rows = csv.DictReader(f)
            vals = []
            for row in rows:
                try:
                    vals.append(float(row.get("net_pnl_rupees") or 0.0))
                except ValueError:
                    vals.append(0.0)
            return vals

    def summary_text(self) -> str:
        s = summarize_pnl(self.load_net_pnls())
        return (
            f"Trades: {s.trades}\n"
            f"Wins: {s.wins}\n"
            f"Losses: {s.losses}\n"
            f"Win Rate: {s.win_rate:.2%}\n"
            f"Average Win: {s.average_win:.2f}\n"
            f"Average Loss: {s.average_loss:.2f}\n"
            f"Expectancy: {s.expectancy:.2f}\n"
            f"Profit Factor: {s.profit_factor:.2f}\n"
            f"Net PnL: {s.net_pnl:.2f}\n"
            f"Max Drawdown: {s.max_drawdown:.2f}\n"
        )

    def write_html(self, output_path: str | Path) -> Path:
        text = html.escape(self.summary_text())
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"<html><body><h1>Dry Run Report</h1><pre>{text}</pre></body></html>", encoding="utf-8")
        return out


class DashboardHTML:
    @staticmethod
    def write_ranking(output_path: str | Path, rows: Iterable[dict]) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = list(rows)
        headers = sorted({k for r in rows for k in r.keys()}) if rows else []
        body = ""
        if headers:
            body += "<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>"
            for r in rows:
                body += "<tr>" + "".join(f"<td>{html.escape(str(r.get(h, '')))}</td>" for h in headers) + "</tr>"
        out.write_text(
            "<html><body><h1>Paper Opportunity Ranking</h1><table border='1'>" + body + "</table></body></html>",
            encoding="utf-8",
        )
        return out
