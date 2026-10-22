"""Draw the experiment's figures (docs/figures/*.svg) from docs/experiment-results.json.

    python scripts/plot_experiment.py          # (re)write the SVGs
    python scripts/plot_experiment.py --check  # exit 1 if a committed SVG differs

Needs only the committed JSON (scripts/export_experiment_json.py writes it), not the
private data. The same JSON always gives the same bytes: matplotlib is pinned in
requirements-dev.txt, its default style is used whatever your matplotlibrc says, the
SVG ids come from a fixed salt and there is no date in the file.

    accuracy-by-rule.svg   accuracy by rule, with n and the 95% interval
    false-pass-fail.svg    false PASS and false FAIL, against the labels and the set-up state
    review-by-kind.svg     what the AI answered on each kind of picture (NEEDS REVIEW or not)
"""

import io
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window: files only
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import transforms  # noqa: E402
from matplotlib.ticker import MultipleLocator, PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs" / "experiment-results.json"
FIGURES = ROOT / "docs" / "figures"

# The chart surface and inks, and categorical slots 1-4 in their fixed order (blue,
# orange, aqua, yellow): neighbours in this order stay apart for colour-blind readers.
SURFACE, INK, INK_2, MUTED, GRID, AXIS = (
    "#fcfcfb",
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
)
SLOTS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],  # comes with matplotlib: the same widths everywhere
    "font.size": 9,
    "svg.fonttype": "none",  # text stays text
    "svg.hashsalt": "compliancelens-experiment",  # fixed ids, so fixed bytes
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.75,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "xtick.color": AXIS,
    "xtick.labelcolor": INK_2,
    "ytick.left": False,
    "ytick.labelcolor": INK,
    "grid.color": GRID,
    "grid.linewidth": 0.75,
    "text.color": INK,
}
WIDTH, ROW = 7.2, 0.36  # inches: the figure's width, and the height of one row
RULES = {
    "AWS-01": "password length",
    "AWS-02": "MFA for console users",
    "AWS-05": "bucket public access",
    "GH-01": "required reviews",
    "GH-06": "base permission",
}
KINDS = {  # in the order they are drawn, top to bottom
    "plain": "plain (for comparison)",
    "dark": "dark theme",
    "small": "small text",
    "injection": "prompt injection",
    "fold": "below the fold",
    "covered": "setting covered",
    "review": "unclear on purpose",
}
ANSWERS = (  # what the AI answered, against the label
    ("right", "right PASS / FAIL"),
    ("wrong", "wrong PASS / FAIL"),
    ("review_ok", "NEEDS REVIEW, labelled REVIEW"),
    ("review_clear", "NEEDS REVIEW on a clear picture"),
)


def _figure(rows: int, title: str, subtitle: str, legend: int, left: float, right: float):
    """A figure with a title, a subtitle, `legend` lines for a legend, and one plot of
    `rows` rows.
    `left` and `right` are the inches kept for the row names and the right-hand column.
    Returns the figure, the plot and where the legend goes (figure coordinates)."""
    top, bottom = 0.72 + 0.24 * legend + (0.06 if legend else 0), 0.42
    height = top + rows * ROW + bottom
    fig = plt.figure(figsize=(WIDTH, height))
    ax = fig.add_axes(
        (left / WIDTH, bottom / height, 1 - (left + right) / WIDTH, rows * ROW / height)
    )
    fig.text(0.15 / WIDTH, 1 - 0.14 / height, title, fontsize=12, fontweight="bold", va="top")
    fig.text(0.15 / WIDTH, 1 - 0.42 / height, subtitle, color=INK_2, va="top")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.set_ylim(-0.5, rows - 0.5)
    return fig, ax, (0.1 / WIDTH, 1 - 0.64 / height)


def _right_column(ax, y: float, text: str, color: str = INK_2) -> None:
    """Text just right of the plot, on row y."""
    column = transforms.blended_transform_factory(ax.transAxes, ax.transData)
    ax.text(1.03, y, text, transform=column, va="center", color=color)


def _interval(ax, y: float, rate: dict, color: str) -> None:
    """A dot at the rate and a line over its 95% interval."""
    low, high = rate["ci95"]
    ax.plot([low, high], [y, y], color=color, linewidth=2, solid_capstyle="round", clip_on=False)
    ax.plot(
        [rate["value"]],
        [y],
        marker="o",
        markersize=7,
        color=color,
        markeredgecolor=SURFACE,
        markeredgewidth=1.5,
        clip_on=False,
    )


def _legend(fig, where, handles, names, columns: int) -> None:
    fig.legend(
        handles,
        names,
        loc="upper left",
        bbox_to_anchor=where,
        ncol=columns,
        frameon=False,
        labelcolor=INK_2,
        handlelength=1.6,
        columnspacing=1.4,
    )


def accuracy_by_rule(data: dict):
    """Accuracy of each rule's answers and of all of them, with n and the 95% interval."""
    rows = [("All rules", data["overall"]["accuracy"])]
    rows += [
        (f"{rule}  {RULES.get(rule, '')}".strip(), rates["accuracy"])
        for rule, rates in data["by_rule"].items()
    ]
    fig, ax, _ = _figure(
        len(rows),
        "AI accuracy by rule",
        f"Answers that match the final label ({data['repeats']} answers per case);"
        " dot = share, line = 95% interval",
        legend=0,
        left=2.0,
        right=1.3,
    )
    for y, (_, rate) in enumerate(reversed(rows)):
        _interval(ax, y, rate, SLOTS[0])
        _right_column(ax, y, f"{rate['value']:.0%}   {rate['k']} of {rate['n']}")
    ax.axhline(len(rows) - 1.5, color=AXIS, linewidth=0.75)
    ax.set_yticks(range(len(rows)), [name for name, _ in reversed(rows)])
    ax.get_yticklabels()[-1].set_fontweight("bold")
    ax.set_xlim(0.5, 1.0)
    return fig


def false_pass_fail(data: dict):
    """False PASS and false FAIL, scored against the labels and against the set-up state."""
    series = (
        ("against the labels", data["overall"]),
        ("against the set-up state", data["vs_state"]),
    )
    rows = (("False PASS", "false_pass"), ("False FAIL", "false_fail"))
    fig, ax, where = _figure(
        2 * len(rows),
        "Wrong PASS and wrong FAIL answers",
        "False PASS: FAIL pictures called PASS. False FAIL: PASS pictures called FAIL."
        " Line = 95% interval.",
        legend=1,
        left=1.2,
        right=0.3,
    )
    highest = 0.0
    for y, (_, key) in enumerate(reversed(rows)):
        for offset, (_, rates), color in zip((0.45, -0.45), series, SLOTS, strict=False):
            rate = rates[key]
            row = 2 * y + 0.5 + offset
            _interval(ax, row, rate, color)
            highest = max(highest, rate["ci95"][1])
            ax.text(
                rate["ci95"][1] + 0.005,
                row,
                f"  {rate['value']:.0%} ({rate['k']} of {rate['n']})",
                va="center",
                color=INK_2,
            )
    ax.set_yticks([2 * y + 0.5 for y in range(len(rows))], [name for name, _ in reversed(rows)])
    ax.set_ylim(-0.5, 2 * len(rows) - 0.5)
    ax.set_xlim(0, min(1.0, (int(highest * 20) + 2) / 20))
    ax.xaxis.set_major_locator(MultipleLocator(0.05))
    handles = [
        ax.plot([], [], marker="o", markersize=7, linewidth=2, color=color)[0]
        for _, color in zip(series, SLOTS, strict=False)
    ]
    _legend(fig, where, handles, [name for name, _ in series], columns=len(series))
    return fig


def answer_counts(rates: dict) -> dict:
    """How many answers were a right PASS/FAIL, a wrong PASS/FAIL, NEEDS REVIEW on a
    picture labelled REVIEW, and NEEDS REVIEW on a clear one, from one group's rates."""
    decided, recall, coverage = rates["decided_accuracy"], rates["review_recall"], rates["coverage"]
    return {
        "right": decided["k"],
        "wrong": decided["n"] - decided["k"] + recall["n"] - recall["k"],
        "review_ok": recall["k"],
        "review_clear": coverage["n"] - coverage["k"],
    }


def review_by_kind(data: dict):
    """What the AI answered on each kind of picture, as shares of its answers."""
    kinds = [kind for kind in KINDS if kind in data["by_kind"]]
    kinds += [kind for kind in data["by_kind"] if kind not in KINDS]
    fig, ax, where = _figure(
        len(kinds),
        "What the AI answered, by kind of picture",
        f"Share of the answers ({data['repeats']} per case), compared with the final label",
        legend=2,
        left=1.75,
        right=1.6,
    )
    for y, kind in enumerate(reversed(kinds)):
        counts = answer_counts(data["by_kind"][kind])
        total = sum(counts.values())
        left = 0.0
        for (key, _), color in zip(ANSWERS, SLOTS, strict=True):
            share = counts[key] / total
            if share:
                ax.barh(y, share, left=left, height=0.6, color=color, edgecolor=SURFACE, lw=1.5)
            if share >= 0.04:  # a count only where it fits
                ax.text(left + share / 2, y, counts[key], ha="center", va="center", fontsize=8)
            left += share
        cases = total // data["repeats"]
        _right_column(ax, y, f"{total} answers, {cases} case{'' if cases == 1 else 's'}")
    ax.set_yticks(range(len(kinds)), [KINDS.get(kind, kind) for kind in reversed(kinds)])
    ax.set_xlim(0, 1)
    handles = [plt.Rectangle((0, 0), 1, 1, color=color) for color in SLOTS]
    _legend(fig, where, handles, [name for _, name in ANSWERS], columns=2)
    return fig


FIGURES_TO_DRAW = {
    "accuracy-by-rule.svg": accuracy_by_rule,
    "false-pass-fail.svg": false_pass_fail,
    "review-by-kind.svg": review_by_kind,
}


def svg(draw, data: dict) -> bytes:
    """One figure as SVG bytes: the same data always gives the same bytes."""
    with matplotlib.rc_context():
        matplotlib.rcdefaults()  # whatever your matplotlibrc says
        matplotlib.rcParams.update(STYLE)
        fig = draw(data)
        out = io.BytesIO()
        fig.savefig(out, format="svg", metadata={"Date": None})
        plt.close(fig)
    return out.getvalue()


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    differ = []
    for name, draw in FIGURES_TO_DRAW.items():
        path = FIGURES / name
        image = svg(draw, data)
        if check:
            if not path.is_file() or path.read_bytes() != image:
                differ.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image)
            print(f"wrote {path.relative_to(ROOT).as_posix()} ({len(image):,} bytes)")
    for name in differ:
        print(f"{name} differs from scripts/plot_experiment.py: run it without --check")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
