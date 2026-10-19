"""Heuristic check that a manuscript follows REVTeX 4.2 / APS conventions.

Rules are taken from the public APS Author Guide for REVTeX 4.2 and the
REVTeX 4.2 Author's Guide (CTAN / journals.aps.org/revtex):

- ``\\documentclass[...]{revtex4-2}`` with a society option (``aps``/``aip``/...)
  and a journal option; drafting with ``preprint`` is expected.
- Front matter uses ``\\title``, ``\\author``, ``\\affiliation``, ``\\date``,
  ``\\maketitle`` (and ``\\begin{abstract}`` when an abstract is present).
- Bibliography: ``\\bibliography{...}`` only — do **not** set
  ``\\bibliographystyle``; the class selects the style.
- Citations use natbib commands already provided by REVTeX
  (``\\cite``, ``\\onlinecite``, ``\\citet``, ``\\citep``, ...), not the
  ``cite`` package.
- Do not load packages that fight REVTeX float/caption handling:
  ``cite``, ``caption``, ``subcaption``, ``hyperref`` (unless you know you
  need it), ``float``'s ``[H]`` placement.
- Figures via ``graphicx`` / ``\\includegraphics``; tables via ``tabular`` /
  ``ruledtabular`` / ``longtable`` as appropriate.
- Sectioning with ``\\section`` / ``\\subsection`` / ``\\subsubsection``;
  acknowledgments in the ``acknowledgments`` environment.

Usage:
  python support/check-revtex/check_revtex.py
  python support/check-revtex/check_revtex.py --latex latex
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
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
DOCUMENTCLASS_RE = re.compile(
    r"\\documentclass(?:\[([^\]]*)\])?\{([^}]+)\}", re.S
)
USEPACKAGE_RE = re.compile(
    r"\\usepackage(?:\[([^\]]*)\])?\{([^}]+)\}"
)

# Packages documented as incompatible or commonly breaking REVTeX.
BAD_PACKAGES = {
    "cite": "REVTeX loads natbib; do not load cite.sty",
    "caption": "incompatible with revtex4-2 caption handling",
    "subcaption": "incompatible with revtex4-2; use minipage panels instead",
    "subfig": "conflicts with REVTeX float captions",
    "natbib": "already loaded by REVTeX",
}

SOCIETY_OPTIONS = {"aps", "aip", "aapm", "sor"}
LAYOUT_OPTIONS = {"preprint", "reprint", "twocolumn", "onecolumn", "lengthcheck"}
APS_JOURNALS = {
    "pra", "prb", "prc", "prd", "pre", "prl", "prx", "rmp",
    "prab", "prper", "prapplied", "prfluids", "prmaterials",
    "prresearch", "praccelbeams",
}

CITE_OK = {
    "cite", "onlinecite", "citet", "citep", "citealt", "citealp",
    "citeauthor", "citeyear", "citeyearpar", "nocite",
}


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


def read_tex_tree(main: Path) -> tuple[str, list[tuple[Path, str]]]:
    base = main.parent
    seen: set[Path] = set()
    ordered: list[tuple[Path, str]] = []

    def add(path: Path) -> None:
        path = path.resolve()
        if path in seen or not path.is_file():
            return
        seen.add(path)
        text = strip_comments(path.read_text(encoding="utf-8"))
        ordered.append((path, text))
        for match in INPUT_RE.finditer(text):
            rel = match.group(1)
            if not rel.endswith(".tex"):
                rel = rel + ".tex"
            add((base / rel).resolve())

    add(main.resolve())
    combined = "\n".join(text for _, text in ordered)
    return combined, ordered


def split_options(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [opt.strip() for opt in raw.replace("\n", "").split(",") if opt.strip()]


def check(latex_dir: Path) -> Report:
    report = Report()
    main = latex_dir / "main.tex"
    if not main.is_file():
        report.error(f"missing {main}")
        return report

    combined, files = read_tex_tree(main)
    main_text = files[0][1]

    dc = DOCUMENTCLASS_RE.search(main_text)
    if not dc:
        report.error("main.tex: no \\documentclass found")
        return report

    options = split_options(dc.group(1))
    classname = dc.group(2).strip()
    option_set = {opt.lower() for opt in options}

    if classname != "revtex4-2":
        report.error(
            f"document class is `{classname}`; APS/AIP submissions use revtex4-2"
        )
    else:
        if not option_set & SOCIETY_OPTIONS:
            report.error(
                "revtex4-2 needs a society option (aps, aip, aapm, or sor)"
            )
        if "aps" in option_set and not option_set & APS_JOURNALS:
            report.warn(
                "APS class option without a journal option "
                "(pra, prl, prd, ...); using a journal option is recommended"
            )
        if not option_set & LAYOUT_OPTIONS:
            report.warn(
                "no preprint/reprint/twocolumn option; "
                "APS Author Guide recommends preprint while drafting"
            )
        if "letterpaper" not in option_set and "a4paper" in option_set:
            report.warn(
                "a4paper is set; APS Author Guide recommends letter size "
                "for referee printing (acceptable for internal CDR drafts)"
            )
        if "superscriptaddress" not in option_set and "groupedaddress" not in option_set:
            report.warn(
                "neither superscriptaddress nor groupedaddress is set; "
                "REVTeX defaults to grouped addresses"
            )

    for match in USEPACKAGE_RE.finditer(main_text):
        for pkg in split_options(match.group(2)):
            pkg = pkg.strip()
            if pkg in BAD_PACKAGES:
                report.error(f"\\usepackage{{{pkg}}}: {BAD_PACKAGES[pkg]}")
            if pkg == "hyperref":
                report.warn(
                    "hyperref can interact badly with REVTeX; "
                    "load it last and test bookmarks/citations"
                )
            if pkg == "placeins":
                report.warn(
                    "placeins/\\FloatBarrier often creates large empty regions; "
                    "prefer softer float parameters with floatfix"
                )

    # Front matter
    for cmd in (r"\title", r"\author", r"\affiliation", r"\maketitle"):
        if cmd not in main_text and cmd.replace("\\", "\\\\") not in main_text:
            # simple containment
            pass
    if r"\title{" not in main_text and r"\title " not in main_text:
        report.error("missing \\title{...}")
    if r"\author{" not in main_text:
        report.error("missing \\author{...}")
    if r"\affiliation{" not in main_text:
        report.warn("no \\affiliation{...} found")
    if r"\maketitle" not in main_text:
        report.error("missing \\maketitle")
    if r"\date{" not in main_text and r"\date " not in main_text:
        report.warn("no \\date{...}; REVTeX Author's Guide uses \\date{\\today}")

    # Bibliography
    if r"\bibliographystyle" in combined:
        report.error(
            "\\bibliographystyle is set; REVTeX selects the style from class options"
        )
    if not re.search(r"\\bibliography\{[^}]+\}", combined):
        report.error("missing \\bibliography{...}")

    # Incompatible float placement
    if re.search(r"\\begin\{figure\*?}\s*\[H\]", combined):
        report.error(
            "figure uses [H] placement; REVTeX/APS guides expect [htbp]/floatfix"
        )
    if re.search(r"\\begin\{table\*?}\s*\[H\]", combined):
        report.error(
            "table uses [H] placement; prefer [htbp] / floatfix"
        )

    # Captions package commands
    if r"\captionof{" in combined or r"\subcaption" in combined:
        report.error("caption/subcaption commands found; not compatible with REVTeX")

    # Citation commands outside the allowed natbib set
    for match in re.finditer(r"\\([A-Za-z]+)(?:\*|)", combined):
        name = match.group(1)
        if name in {"Cite", "Citet", "citep"}:
            report.warn(
                f"\\{name} is unusual; REVTeX/natbib prefer "
                "\\cite / \\citet / \\citep / \\onlinecite"
            )

    # Sectioning presence
    if r"\section{" not in combined and r"\section*{" not in combined:
        report.warn("no \\section found in the manuscript body")

    # Acknowledgments
    if "acknowledgments" not in combined and "acknowledgements" not in combined:
        report.warn(
            "no acknowledgments environment "
            "(APS style uses \\begin{acknowledgments}...\\end{acknowledgments})"
        )

    # graphicx for figures
    if r"\includegraphics" in combined and "graphicx" not in main_text:
        # may be loaded by class in some setups; warn only
        report.warn("\\includegraphics used but graphicx not loaded in main.tex")

    # Class options that load amsmath
    if r"\usepackage{amsmath}" in main_text and "amsmath" in option_set:
        report.warn(
            "amsmath loaded both as a class option and via \\usepackage; prefer the class option"
        )

    # floatfix recommended when many floats
    n_figures = len(re.findall(r"\\begin\{figure\*?}", combined))
    if n_figures >= 10 and "floatfix" not in option_set:
        report.warn(
            f"{n_figures} figures but no floatfix class option; "
            "APS Author Guide recommends floatfix for dense manuscripts"
        )

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
    print(
        f"OK: REVTeX heuristics passed "
        f"({len(report.warnings)} warning(s); see APS Author Guide for REVTeX 4.2)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
