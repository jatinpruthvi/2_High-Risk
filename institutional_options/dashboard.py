from __future__ import annotations

import html
from pathlib import Path

from .models import SelectionResult


class DryRunDashboard:
    """Operational dry-run dashboard renderer.

    Produces a self-contained HTML snapshot of the latest ranking cycle. It is intentionally
    dependency-free and suitable for paper-mode monitoring and audit snapshots.
    """

    @staticmethod
    def render_selection(result: SelectionResult) -> str:
        rows = []
        for e in result.evaluations:
            c = e.candidate
            rows.append({
                "instrument": c.instrument.underlying,
                "side": c.side.value,
                "decision": e.decision.value,
                "grade": e.grade.value,
                "score": f"{e.comparable_opportunity_score:.2f}",
                "threshold": f"{e.dynamic_excellent_threshold:.2f}",
                "contract_quality": f"{e.contract_quality.score:.2f}",
                "premium_elasticity": f"{c.premium_elasticity:.2f}",
                "market_hostility": f"{c.market_hostility_score:.2f}",
                "iv_crush": f"{c.iv_crush_risk_score:.2f}",
                "eligible": str(e.eligible),
                "reasons": "; ".join(e.reasons),
            })
        selected = result.selected
        selected_text = "NONE"
        if selected is not None:
            selected_text = f"{selected.candidate.instrument.underlying} {selected.candidate.side.value} grade={selected.grade.value} score={selected.comparable_opportunity_score:.2f}"
        headers = list(rows[0].keys()) if rows else []
        table = ""
        if rows:
            table += "<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>"
            for r in rows:
                table += "<tr>" + "".join(f"<td>{html.escape(str(r[h]))}</td>" for h in headers) + "</tr>"
        return f"""
<html><head><title>Dry Run Dashboard</title></head><body>
<h1>Dry Run Opportunity Ranking</h1>
<p><b>Decision:</b> {html.escape(result.decision.value)}</p>
<p><b>Selected:</b> {html.escape(selected_text)}</p>
<p><b>Reasons:</b> {html.escape('; '.join(result.reasons))}</p>
<table border="1" cellspacing="0" cellpadding="4">{table}</table>
</body></html>
"""

    @staticmethod
    def write_selection(path: str | Path, result: SelectionResult) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DryRunDashboard.render_selection(result), encoding="utf-8")
        return p
