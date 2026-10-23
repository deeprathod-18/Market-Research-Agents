"""Matplotlib chart helpers (headless 'Agg' backend). Each returns the saved file path or None."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..state import EntityFinancials  # noqa: E402

PALETTE = ["#1F4E79", "#C55A11", "#548235", "#7F6000", "#7030A0", "#2E75B6"]


def price_chart(entities: List[EntityFinancials], path: Path, title: str = "Indexed share price (start = 100)") -> Optional[str]:
    ents = [e for e in entities if len(e.closes) > 5]
    if not ents:
        return None
    n = min(len(e.closes) for e in ents)
    n = min(n, 504)
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, e in enumerate(ents):
        series = e.closes[-n:]
        base = series[0] or 1.0
        ax.plot(range(n), [v / base * 100 for v in series], label=e.name, color=PALETTE[i % len(PALETTE)],
                linewidth=2.2 if e.is_target else 1.5)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel("Trading days (most recent window)")
    ax.set_ylabel("Index")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)


def bar_chart(rows: List[Dict], label_key: str, value_key: str, path: Path, title: str, pct: bool = False) -> Optional[str]:
    pts = [(r[label_key], r.get(value_key)) for r in rows if isinstance(r.get(value_key), (int, float))]
    if not pts:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    labels, vals = zip(*pts)
    bars = ax.bar(labels, vals, color=[PALETTE[i % len(PALETTE)] for i in range(len(vals))])
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.1f}%" if pct else f"{v:,.1f}", (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.25)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return str(path)
