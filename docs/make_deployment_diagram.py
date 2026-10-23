"""Generates docs/deployment_architecture.png (used in the README and the report)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).parent / "deployment_architecture.png"
fig, ax = plt.subplots(figsize=(14, 7.2))
ax.set_xlim(0, 14)
ax.set_ylim(0, 7.2)
ax.axis("off")
NAVY, ORANGE, GREEN, GREY, PURPLE, BLUE = "#1F4E79", "#C55A11", "#548235", "#EAF1F8", "#7030A0", "#2E75B6"


def box(x, y, w, h, text, fc, tc="white", fs=9.5, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.1", fc=fc, ec="none"))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc, fontsize=fs, fontweight="bold" if bold else "normal")


def arrow(x1, y1, x2, y2, color="#333"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5))


# Developer and CI
box(0.2, 6.0, 2.2, 1.0, "Developer\n(git push)", "#595959")
box(3.0, 6.0, 2.6, 1.0, "GitHub repository\n+ Actions CI (tests,\nDocker build)", "#24292e", fs=8.5)
arrow(2.4, 6.5, 3.0, 6.5)
arrow(4.3, 6.0, 4.3, 5.2, "#24292e")
ax.text(4.45, 5.55, "deploy: build image", fontsize=8, color="#24292e")

# Container
ax.add_patch(FancyBboxPatch((0.2, 0.3), 9.2, 4.9, boxstyle="round,pad=0.02,rounding_size=0.15", fc="#F7FAFD", ec=NAVY, lw=2, ls="--"))
ax.text(0.45, 4.85, "Hosting platform: Docker container (Hugging Face Space / Render / local Docker)", fontsize=10, fontweight="bold", color=NAVY)
box(0.5, 3.2, 2.4, 0.9, "Streamlit UI\n(app.py)", GREEN)
box(0.5, 4.2, 2.4, 0.45, "Secrets: API key, access code", PURPLE, fs=7.5)
box(3.3, 2.0, 5.8, 2.3, "", NAVY)
ax.text(6.2, 4.0, "LangGraph orchestrator (shared state)", color="white", fontsize=10, fontweight="bold", ha="center")
for i, (t, c) in enumerate([("1\nResearcher", BLUE), ("Quality\ngate", ORANGE), ("2\nData\nAnalyst", BLUE), ("3\nStrategy\nConsultant", BLUE), ("4\nReport\nWriter", BLUE)]):
    box(3.45 + i * 1.12, 2.15, 1.0, 1.55, t, c, fs=8)
    if i:
        arrow(3.45 + i * 1.12 - 0.12, 2.9, 3.45 + i * 1.12, 2.9, "white")
box(3.3, 0.5, 5.8, 1.0, "LLMClient (provider-agnostic)  +  tools layer:\nweb search | Wikipedia | market data | charts | DOCX export", GREY, tc="#222", fs=8.5, bold=False)
box(0.5, 1.0, 2.4, 0.9, "Outputs (ephemeral disk)\nreport.docx, report.md,\nrun_summary.json", GREY, tc="#222", fs=8, bold=False)
arrow(2.9, 3.65, 3.3, 3.4)
arrow(6.2, 2.0, 6.2, 1.5)
arrow(3.3, 1.2, 2.9, 1.3)

# User
box(10.2, 3.0, 1.5, 1.0, "User\n(browser)", "#595959")
ax.plot([10.95, 10.95, 3.1, 3.1], [4.0, 4.58, 4.58, 3.75], color=GREEN, lw=1.5)
arrow(3.1, 3.75, 2.9, 3.75, GREEN)
ax.text(7.0, 4.64, "HTTPS requests and responses", fontsize=8.5, color=GREEN, ha="center")

# External services
ax.text(12.4, 6.95, "External services", fontsize=10, fontweight="bold", color=NAVY, ha="center")
svc = [("LLM provider API\n(Groq, Gemini, OpenAI,\nAnthropic, OpenRouter)", ORANGE, 5.7, 1.0), ("DuckDuckGo search", "#7F6000", 4.6, 0.7),
       ("Wikipedia REST API", "#7F6000", 1.9, 0.7), ("Yahoo Finance (yfinance)", "#7F6000", 0.9, 0.7)]
for t, c, y, h in svc:
    box(10.4, y, 3.3, h, t, c, fs=8.5)
arrow(9.1, 3.9, 10.4, 6.2, ORANGE)
arrow(9.1, 3.6, 10.4, 4.95, "#7F6000")
arrow(9.1, 2.4, 10.4, 2.25, "#7F6000")
arrow(9.1, 1.2, 10.4, 1.25, "#7F6000")
ax.text(7.0, 0.05, "Stateless container: scale by adding instances. Keys live in the platform secrets store, never in the image or the repository.",
        ha="center", fontsize=8.5, color="#444")
fig.savefig(OUT, dpi=160, bbox_inches="tight")
print("saved", OUT)
