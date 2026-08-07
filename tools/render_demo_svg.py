"""Render the README's animated demo from the demo's REAL output.

    python tools/render_demo_svg.py          # rewrites assets/demo.svg

The SVG is generated from a fresh run of `python -m agentattest.demo`, never
from pasted text, so the image cannot drift from what the code actually prints.
If the demo's wording changes, rerunning this script is the whole update.

Only the first four acts are drawn -- the claims story, which is the hook.
The caption under the image in the README says exactly that, and the remaining acts
appear as plain code blocks further down. An asset that shows less than the
whole demo is fine; an asset that shows something the demo does not print is
not, which is why this script refuses to render if the expected act markers
are missing from the live output.

Animation is plain CSS inside the SVG (per-line keyframes on a shared clock),
which GitHub's README image pipeline renders fine. No external tools, no
recording software, a few KB on disk, crisp at any zoom.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "demo.svg"

# Layout constants. Tuned for GitHub's light and dark README backgrounds --
# the SVG carries its own dark terminal background either way.
FONT = 13.5
LINE_H = 21
CHAR_W = 8.15
WRAP = 88
PAD_X = 18
PAD_TOP = 52          # below the title bar
PAD_BOTTOM = 16
SECONDS_PER_LINE = 0.55
HOLD_SECONDS = 6.0    # everything visible before the loop restarts

BG = "#0d1117"
BAR = "#161b22"
FG = "#c9d1d9"
DIM = "#8b949e"
HEAD = "#e6edf3"
QUOTE = "#79c0ff"
RED = "#f85149"
GREEN = "#3fb950"


def demo_lines() -> list[str]:
    """Acts 1-4 of the live demo, verbatim."""
    proc = subprocess.run(
        [sys.executable, "-m", "agentattest.demo"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(f"demo exited {proc.returncode}; not rendering from a broken demo")
    out = proc.stdout.splitlines()

    starts = [i for i, ln in enumerate(out)
              if ln.startswith(("1. ", "2. ", "3. ", "4. ", "5. "))]
    if len(starts) < 5:
        raise SystemExit(
            "demo output no longer contains acts 1-5 where expected; "
            "refusing to render a stale or partial story"
        )
    lines = out[starts[0]:starts[4]]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def wrap(line: str) -> list[str]:
    """Soft-wrap long lines, keeping the indent so structure survives.

    A continuation is indented two spaces past the original line's indent, so a
    wrapped finding still reads as part of its block rather than a new item.
    """
    if len(line) <= WRAP:
        return [line]
    lead = line[:len(line) - len(line.lstrip(" "))]
    return textwrap.wrap(
        line.strip(), width=WRAP,
        initial_indent=lead, subsequent_indent=lead + "  ",
    )


def color_for(line: str) -> tuple[str, bool]:
    """(fill, bold) for one demo line, by what it is rather than position."""
    s = line.strip()
    if s.startswith(("1.", "2.", "3.", "4.")):
        return HEAD, True
    if s.startswith("| "):
        return QUOTE, False
    if s.startswith("-> REFUSED"):
        return RED, True
    if s.startswith("-> allowed"):
        return GREEN, True
    if s.startswith(("Turn refused", "x line")):
        return RED, False
    if set(s) <= {"-"}:
        return DIM, False
    return FG, False


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render(lines: list[str]) -> str:
    rows: list[tuple[str, str, bool]] = []
    for line in lines:
        fill, bold = color_for(line)
        for piece in wrap(line):
            rows.append((piece, fill, bold))

    width = int(WRAP * CHAR_W + 2 * PAD_X)
    height = int(PAD_TOP + LINE_H * len(rows) + PAD_BOTTOM)
    total = round(len(rows) * SECONDS_PER_LINE + HOLD_SECONDS, 1)

    css = [f".l{{font:{'%g' % FONT}px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
           f"white-space:pre}}"]
    texts = []
    for i, (text, fill, bold) in enumerate(rows):
        t_on = i * SECONDS_PER_LINE
        p_on = round(t_on / total * 100, 2)
        p_vis = round(min(p_on + 0.6, 99.0), 2)
        css.append(
            f"@keyframes r{i}{{0%,{p_on}%{{opacity:0}}{p_vis}%,98%{{opacity:1}}"
            f"100%{{opacity:0}}}}"
            f".r{i}{{opacity:0;animation:r{i} {total}s linear infinite}}"
        )
        weight = ' font-weight="bold"' if bold else ""
        y = PAD_TOP + LINE_H * (i + 1) - 6
        texts.append(
            f'<text class="l r{i}" x="{PAD_X}" y="{y}" fill="{fill}"{weight}>'
            f"{esc(text)}</text>"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="python -m agentattest.demo: an unbacked claim is refused; the same claim with a test result attached is allowed; honest uncertainty is left alone; all-done is checked against the list of what was asked">
<style>{''.join(css)}</style>
<rect width="{width}" height="{height}" rx="9" fill="{BG}"/>
<path d="M0 9a9 9 0 0 1 9-9h{width - 18}a9 9 0 0 1 9 9v27H0z" fill="{BAR}"/>
<circle cx="22" cy="18" r="5.5" fill="#ff5f57"/>
<circle cx="42" cy="18" r="5.5" fill="#febc2e"/>
<circle cx="62" cy="18" r="5.5" fill="#28c840"/>
<text class="l" x="{width // 2}" y="23" fill="{DIM}" text-anchor="middle">python -m agentattest.demo</text>
{chr(10).join(texts)}
</svg>
"""


def main() -> int:
    lines = demo_lines()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    svg = render(lines)
    OUT.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(svg):,} bytes, {len(lines)} demo lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
