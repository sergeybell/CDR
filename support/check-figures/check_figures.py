"""Check that every figure in a LaTeX tree is cited in the body text.

For each ``figure`` / ``figure*`` environment the script requires:
- at least one ``\\includegraphics``;
- a ``\\label{fig:...}`` (or any ``\\label{...}``) inside the environment;
- at least one ``\\ref`` / ``\\pageref`` / ``\\cref`` to that label in the
  surrounding ``.tex`` sources, outside comment lines and outside that
  figure's own caption block.

It also reports image files under ``img/`` that are never included, and
``\\includegraphics`` paths that do not resolve under ``\\graphicspath``.

Usage:
  python support/check-figures/check_figures.py
  python support/check-figures/check_figures.py --latex latex
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_LATEX = ROOT / "latex"

COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)
GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:\{[^}]*\})+)\}")
INCLUDE_RE = re.compile(
    r"\\includegraphics\*?(?:\[[^\]]*\])?\{([^}]+)\}"
)
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(
    r"\\(?:eq)?(?:page)?ref\*?(?:\[[^\]]*\])?\{([^}]+)\}"
    r"|\\(?:[cC]ref|autoref|eqref)\*?\{([^}]+)\}"
)
BEGIN_FIG_RE = re.compile(r"\\begin\{figure\*?\}")
END_FIG_RE = re.compile(r"\\end\{figure\*?\}")
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")


@dataclass
class Figure:
    file: Path
    line: int
    label: str | None
    images: list[str]
    env_text: str


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub("", text)


def read_tex_tree(main: Path) -> list[tuple[Path, str]]:
    """Return (path, comment-stripped text) for main and all \\input files."""
    base = main.parent
    seen: set[Path] = set()
    ordered: list[tuple[Path, str]] = []

    def add(path: Path) -> None:
        path = path.resolve()
        if path in seen or not path.is_file():
            return
        seen.add(path)
        raw = path.read_text(encoding="utf-8")
        text = strip_comments(raw)
        ordered.append((path, text))
        for match in INPUT_RE.finditer(text):
            rel = match.group(1)
            if not rel.endswith(".tex"):
                rel = rel + ".tex"
            add((base / rel).resolve())

    add(main.resolve())
    return ordered


def graphicspaths(main_text: str, main_dir: Path) -> list[Path]:
    paths = [main_dir]
    for match in GRAPHICSPATH_RE.finditer(main_text):
        for inner in re.findall(r"\{([^}]*)\}", match.group(1)):
            paths.append((main_dir / inner).resolve())
    return paths


def resolve_image(name: str, search: list[Path]) -> Path | None:
    stem = Path(name)
    candidates = [stem] if stem.suffix else [
        stem.with_suffix(ext)
        for ext in (".pdf", ".png", ".PNG", ".jpg", ".jpeg", ".eps")
    ]
    if stem.suffix:
        candidates = [stem]
    for directory in search:
        for candidate in candidates:
            hit = directory / candidate
            if hit.is_file():
                return hit
            # also try as-is relative to directory when name has path parts
            hit = directory / name
            if hit.is_file():
                return hit
    return None


def extract_figures(path: Path, text: str) -> list[Figure]:
    figures: list[Figure] = []
    pos = 0
    while True:
        begin = BEGIN_FIG_RE.search(text, pos)
        if not begin:
            break
        end = END_FIG_RE.search(text, begin.end())
        if not end:
            break
        env = text[begin.start() : end.end()]
        line = text.count("\n", 0, begin.start()) + 1
        images = INCLUDE_RE.findall(env)
        labels = LABEL_RE.findall(env)
        fig_labels = [lab for lab in labels if lab.startswith("fig:")]
        label = fig_labels[0] if fig_labels else (labels[0] if labels else None)
        figures.append(
            Figure(
                file=path,
                line=line,
                label=label,
                images=images,
                env_text=env,
            )
        )
        pos = end.end()
    return figures


def collect_refs(files: list[tuple[Path, str]], figures: list[Figure]) -> set[str]:
    """Refs in body text, excluding labels' own figure environments."""
    fig_spans: dict[Path, list[tuple[int, int, str | None]]] = {}
    for fig in figures:
        # rebuild spans from file text
        pass

    refs: set[str] = set()
    for path, text in files:
        # blank out figure environments so caption-only refs do not count
        blanked = text
        for begin in BEGIN_FIG_RE.finditer(text):
            end = END_FIG_RE.search(text, begin.end())
            if not end:
                continue
            blanked = (
                blanked[: begin.start()]
                + " " * (end.end() - begin.start())
                + blanked[end.end() :]
            )
        for match in REF_RE.finditer(blanked):
            keys = match.group(1) or match.group(2) or ""
            for key in keys.split(","):
                key = key.strip()
                if key:
                    refs.add(key)
    return refs


def list_img_files(img_dirs: list[Path]) -> set[Path]:
    found: set[Path] = set()
    for directory in img_dirs:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".eps"}:
                found.add(path.resolve())
    return found


def check(latex_dir: Path) -> Report:
    report = Report()
    main = latex_dir / "main.tex"
    if not main.is_file():
        report.error(f"missing {main}")
        return report

    files = read_tex_tree(main)
    main_text = files[0][1]
    search = graphicspaths(main_text, latex_dir)

    figures: list[Figure] = []
    for path, text in files:
        figures.extend(extract_figures(path, text))

    refs = collect_refs(files, figures)
    included: set[Path] = set()

    if not figures:
        report.warn("no figure environments found")

    for fig in figures:
        rel = fig.file.relative_to(latex_dir) if fig.file.is_relative_to(latex_dir) else fig.file
        loc = f"{rel}:{fig.line}"
        if not fig.images:
            report.error(f"{loc}: figure has no \\includegraphics")
        if not fig.label:
            report.error(f"{loc}: figure has no \\label")
        elif fig.label not in refs:
            report.error(
                f"{loc}: figure `{fig.label}` is never referenced in the body text"
            )
        for name in fig.images:
            resolved = resolve_image(name, search)
            if resolved is None:
                report.error(f"{loc}: image `{name}` not found in graphicspath")
            else:
                included.add(resolved.resolve())

    # orphan files under primary img/ only
    primary_img = [p for p in search if p != latex_dir.resolve()]
    if not primary_img:
        primary_img = [latex_dir / "img"]
    for orphan in sorted(list_img_files(primary_img) - included):
        try:
            rel = orphan.relative_to(latex_dir)
        except ValueError:
            rel = orphan
        report.warn(f"image file never included: {rel}")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latex",
        type=Path,
        default=DEFAULT_LATEX,
        help="LaTeX root containing main.tex (default: latex)",
    )
    args = parser.parse_args(argv)
    latex_dir = args.latex if args.latex.is_absolute() else ROOT / args.latex

    report = check(latex_dir)
    for message in report.errors:
        print(f"ERROR: {message}")
    for message in report.warnings:
        print(f"WARNING: {message}")

    if report.errors:
        print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        return 1
    print(f"OK: all figures are referenced ({len(report.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
