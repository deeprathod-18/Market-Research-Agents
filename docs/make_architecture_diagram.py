"""Generates docs/architecture.png (used in the README and the project report)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).parent / "architecture.png"
fig, ax = plt.subplots(figsize=(14, 5.6))
ax.set_xlim(0, 14.4)
ax.set_ylim(0, 5.6)
ax.axis("off")

NAVY, ORANGE, GREEN, GREY = "#1F4E79", "#C55A11", "#548235", "#EAF1F8"


def box(x, y, w, h, text, fc, tc="white", fs=10, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec="none"))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc, fontsize=fs, fontweight="bold" if bold else "normal")


def arrow(x1, y1, x2, y2, style="-|>", color="#333", rad=0.0):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=1.6, connectionstyle=f"arc3,rad={rad}"))


xs = [0.2 + i * 2.4 for i in range(6)]
w, y, h = 2.0, 3.0, 1.2
labels = [("User request\n(company or industry,\nfocus, peers)", "#595959"), ("1. Researcher", NAVY), ("Orchestrator\nquality gate", ORANGE),
          ("2. Data Analyst", NAVY), ("3. Strategy\nConsultant", NAVY), ("4. Report Writer", NAVY)]
for x, (t, c) in zip(xs, labels):
    box(x, y, w, h, t, c)
for a, b in zip(xs[:-1], xs[1:]):
    arrow(a + w, y + h / 2, b, y + h / 2)

tools = [(1, "Tools:\nWeb search (ddgs)\nWikipedia API"), (2, "Rules: >= 8 sources,\n>= 8 findings,\n>= 4 categories"),
         (3, "Tools: yfinance data,\nmetric engine,\nmatplotlib charts"), (4, "LLM reasoning:\nSWOT, Five Forces,\nrecommendations"),
         (5, "Tools: citation check,\npython-docx export")]
for i, t in tools:
    box(xs[i], 1.55, w, 1.05, t, GREY, tc="#222", fs=8.5, bold=False)
    arrow(xs[i] + w / 2, 2.6, xs[i] + w / 2, y, style="-", color="#999")

ax.add_patch(FancyBboxPatch((0.2, 0.25), 14.0, 0.85, boxstyle="round,pad=0.02,rounding_size=0.12", fc="#FFF2CC", ec="#BF9000"))
ax.text(7.2, 0.675, "Shared graph state (LangGraph):  request  |  sources  |  findings  |  financials  |  analysis  |  strategy  |  report  |  trace",
        ha="center", va="center", fontsize=10, color="#5a4400", fontweight="bold")

arrow(xs[2] + 0.5, y + h, xs[1] + w - 0.5, y + h, color=ORANGE, rad=0.55)
ax.text((xs[1] + xs[2] + w) / 2, 5.0, "retry with broader queries\n(if evidence is thin, max 2 attempts)", ha="center", fontsize=8.5, color=ORANGE)
ax.text(xs[5] + w / 2, 4.45, "report.docx | report.md\nrun_summary.json", ha="center", fontsize=8.5, color="#333")
arrow(xs[5] + w / 2, y + h, xs[5] + w / 2, 4.3, color="#333")
ax.text(xs[2] + w / 2, 2.78, "", fontsize=1)
fig.savefig(OUT, dpi=170, bbox_inches="tight")
print("saved", OUT)
