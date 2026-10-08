"""Build an editable Word version of the CDR contribution from the LaTeX sources.

Pandoc cannot read REVTeX, siunitx, todonotes, longtable or the local ``panel``
environment, and its DOCX writer neither numbers equations nor resolves
``\\ref``. The sources are therefore rewritten into plain LaTeX with all
numbers resolved before pandoc runs.

Usage: python support/tex-to-docx/build_docx.py [output.docx]
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LATEX = ROOT / "latex"
IMG = LATEX / "img"
BIB = LATEX / "bib" / "references.bib"
CSL = HERE / "american-physics-society.csl"
DEFAULT_OUT = ROOT / "authors" / "ЮВСеничев" / "CDR_contribution.docx"

SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def braced(text, start):
    """Return (content, end) of the brace group opening at text[start]."""
    assert text[start] == "{", text[start:start + 40]
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{" and text[i - 1] != "\\":
            depth += 1
        elif text[i] == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    raise ValueError("unbalanced braces at " + text[start:start + 40])


def replace_command(text, name, render, optional=False, nargs=1):
    """Replace every \\name[opt]{arg}... with render(opt, *args, pos)."""
    pattern = re.compile(r"\\" + name + r"(?![A-Za-z])")
    out, pos = [], 0
    while (m := pattern.search(text, pos)):
        i, opt = m.end(), None
        if optional and text.startswith("[", i):
            j = text.index("]", i)
            opt, i = text[i + 1:j], j + 1
        args = []
        for _ in range(nargs):
            while text[i].isspace():
                i += 1
            arg, i = braced(text, i)
            args.append(arg)
        out.append(text[pos:m.start()])
        out.append(render(opt, *args, m.start()))
        pos = i
    out.append(text[pos:])
    return "".join(out)


def strip_comments(text):
    return re.sub(r"(?<!\\)%.*", "", text)


# ---------------------------------------------------------------------------
# Front matter from main.tex
# ---------------------------------------------------------------------------

def parse_main():
    main = strip_comments((LATEX / "main.tex").read_text(encoding="utf-8"))
    body = main[main.index(r"\begin{document}"):]
    title, _ = braced(body, body.index(r"\title") + len(r"\title"))

    groups, names = [], []
    for kind, value in re.findall(r"\\(author|affiliation)\{([^}]*)\}", body):
        if kind == "author":
            names.append(value)
        else:
            groups.append(f"{', '.join(names)} ({value})")
            names = []

    ack = re.search(r"\\begin\{acknowledgments\}(.*?)\\end\{acknowledgments\}",
                    body, re.S).group(1).strip()
    chapters = re.findall(r"\\input\{(chapters/[^}]+)\}", body)
    return title, groups, ack, chapters


# ---------------------------------------------------------------------------
# Structural rewrites (before numbering)
# ---------------------------------------------------------------------------

def convert_longtables(text):
    def repl(m):
        body = m.group(1)
        caption_start = body.index(r"\caption")
        caption, end = braced(body, caption_start + len(r"\caption"))
        label = re.search(r"\\label\{[^}]*\}", body).group(0)
        rows = body[end:]
        rows = re.sub(r"\\label\{[^}]*\}\s*\\\\", "", rows, count=1)
        rows = re.sub(r"\\endfirsthead.*?\\endhead", "", rows, flags=re.S)
        return (f"\\begin{{table}}\n\\caption{{{caption}}}\n{label}\n"
                f"\\begin{{tabular}}{{ll}}\n{rows.strip()}\n\\end{{tabular}}\n"
                f"\\end{{table}}")

    return re.sub(r"\{\\small\s*\\begin\{longtable\}\{[^\n]*\}(.*?)"
                  r"\\end\{longtable\}\s*\}", repl, text, flags=re.S)


def flatten_makecell(text):
    def render(_opt, arg, _pos):
        parts = [p.strip() for p in arg.split(r"\\")]
        joined = parts[0]
        for part in parts[1:]:
            joined = joined[:-1] + part if joined.endswith("-") else f"{joined} {part}"
        return joined

    return replace_command(text, "makecell", render, optional=True)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

NUMBERED = re.compile(r"\\(section|subsection)\{|\\begin\{(figure|table|equation)\}"
                      r"|\\label\{([^}]*)\}")


def collect_labels(text):
    counters = {"figure": 0, "table": 0, "equation": 0}
    section = subsection = 0
    labels, current = {}, None
    for m in NUMBERED.finditer(text):
        if m.group(1) == "section":
            section, subsection = section + 1, 0
            current = str(section)
        elif m.group(1) == "subsection":
            subsection += 1
            current = f"{section}.{subsection}"
        elif m.group(2):
            counters[m.group(2)] += 1
            current = str(counters[m.group(2)])
        else:
            labels[m.group(3)] = current
    return labels


def resolve_refs(text, labels):
    text = replace_command(text, "eqref", lambda _o, key, _p: f"({labels[key]})")
    text = replace_command(text, "ref", lambda _o, key, _p: labels[key])
    return re.sub(r"\\label\{[^}]*\}", "", text)


def number_sections(text):
    section = subsection = 0

    def repl(m):
        nonlocal section, subsection
        if m.group(1) == "section":
            section, subsection = section + 1, 0
            number = f"{section}"
        else:
            subsection += 1
            number = f"{section}.{subsection}"
        return f"\\{m.group(1)}*{{{number} "

    text = re.sub(r"\\(section|subsection)\{", repl, text)
    return text.replace(r"\paragraph{", r"\paragraph*{")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def math_spans(text):
    spans, start = [], None
    for m in re.finditer(r"\\\$|\$|\\begin\{equation\}|\\end\{equation\}", text):
        token = m.group(0)
        if token == r"\$":
            continue
        if token == "$":
            if start is None:
                start = m.start()
            else:
                spans.append((start, m.end()))
                start = None
        elif token.startswith(r"\begin"):
            start = m.start()
        else:
            spans.append((start, m.end()))
            start = None
    return spans


def unit_text(unit):
    unit = unit.replace(".", "·")
    return re.sub(r"\^\{([^}]*)\}", lambda m: m.group(1).translate(SUPERSCRIPT), unit)


def unit_math(unit):
    out = []
    for token in re.split(r"(\.|/|\^\{[^}]*\})", unit):
        if token == ".":
            out.append(r"\cdot ")
        elif token in ("/", "") or token.startswith("^"):
            out.append(token)
        else:
            out.append(rf"\mathrm{{{token}}}")
    return "".join(out)


def convert_units(text):
    spans = math_spans(text)

    def in_math(pos):
        return any(a <= pos < b for a, b in spans)

    # Replacing right to left keeps the precomputed math spans valid.
    for m in reversed(list(re.finditer(r"\\(SI|ang)\{", text))):
        math = in_math(m.start())
        value, end = braced(text, m.end() - 1)
        if m.group(1) == "SI":
            unit, end = braced(text, end)
            new = rf"{value}\,{unit_math(unit)}" if math else f"{value}~{unit_text(unit)}"
        else:
            new = rf"{value}^\circ" if math else f"{value}°"
        text = text[:m.start()] + new + text[end:]
    return text


# ---------------------------------------------------------------------------
# Floats and equations
# ---------------------------------------------------------------------------

def image_path(name):
    path = IMG / f"{name}.png"
    if not path.exists():
        raise FileNotFoundError(path)
    return path.as_posix()


def width_of(options):
    m = re.search(r"width=([0-9.]*)\\(?:textwidth|linewidth)", options or "")
    return float(m.group(1) or 1) if m else 1.0


def convert_figures(text):
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        body = m.group(1)
        cap_start = body.index(r"\caption")
        caption, cap_end = braced(body, cap_start + len(r"\caption"))
        body = body[:cap_start] + body[cap_end:]
        caption = f"\\caption{{Figure {count}. {' '.join(caption.split())}}}"

        if r"\begin{panel}" not in body:
            opts, name = re.search(r"\\includegraphics(?:\[([^\]]*)\])?\{([^}]*)\}",
                                   body).groups()
            graphic = f"\\includegraphics[width={width_of(opts):.2f}\\textwidth]{{{image_path(name)}}}"
            return f"\\begin{{figure}}\n{graphic}\n{caption}\n\\end{{figure}}"

        rows, letter = [], ord("a")
        for row in re.split(r"\\\\(?:\[[^\]]*\])?", body):
            panels = re.findall(r"\\begin\{panel\}(?:\[[^\]]*\])?\{([0-9.]+)\\textwidth\}"
                                r".*?\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", row, re.S)
            if not panels:
                continue
            images = " & ".join(
                f"\\includegraphics[width={float(w):.2f}\\textwidth]{{{image_path(n)}}}"
                for w, n in panels)
            tags = " & ".join(f"({chr(letter + k)})" for k in range(len(panels)))
            letter += len(panels)
            rows.append(f"{images} \\\\\n{tags} \\\\")
        columns = "c" * max(row.count("&") // 2 + 1 for row in rows)
        grid = f"\\begin{{tabular}}{{{columns}}}\n" + "\n".join(rows) + "\n\\end{tabular}"
        return f"\\begin{{figure}}\n{grid}\n{caption}\n\\end{{figure}}"

    return re.sub(r"\\begin\{figure\}(?:\[[^\]]*\])?(.*?)\\end\{figure\}", repl, text,
                  flags=re.S)


def convert_tables(text):
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        body = m.group(1)
        caption, _ = braced(body, body.index(r"\caption") + len(r"\caption"))
        tabular = re.search(r"\\begin\{tabular\}.*?\\end\{tabular\}", body, re.S).group(0)
        caption = " ".join(caption.split())
        return f"\\begin{{table}}\n\\caption{{Table {count}. {caption}}}\n{tabular}\n\\end{{table}}"

    return re.sub(r"\\begin\{table\}(?:\[[^\]]*\])?(.*?)\\end\{table\}", repl, text,
                  flags=re.S)


def convert_equations(text):
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return f"\\[\n{m.group(1).strip()}\n\\qquad ({count})\n\\]"

    return re.sub(r"\\begin\{equation\}(.*?)\\end\{equation\}", repl, text, flags=re.S)


def convert_todos(text):
    return replace_command(
        text, "todo",
        lambda _o, note, _p: f"\n\n\\textbf{{[Note:}} \\emph{{{' '.join(note.split())}}}\\textbf{{]}}\n\n",
        optional=True)


def drop_layout(text):
    text = re.sub(r"~(?=\\cite)", "", text)  # the CSL style inserts its own space
    text = re.sub(r"\\setlength\{\\tabcolsep\}\{[^}]*\}", "", text)
    return re.sub(r"\\(small|footnotesize|centering|hfill)(?![A-Za-z])", "", text)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def build_body(chapters):
    text = "\n\n".join(strip_comments((LATEX / f"{c}.tex").read_text(encoding="utf-8"))
                       for c in chapters)
    text = convert_longtables(text)
    text = flatten_makecell(text)
    labels = collect_labels(text)
    text = convert_units(text)
    text = convert_figures(text)
    text = convert_tables(text)
    text = convert_equations(text)
    text = resolve_refs(text, labels)
    text = number_sections(text)
    text = convert_todos(text)
    return drop_layout(text)


def contents_block(body):
    """Plain-text contents. A Word TOC field makes Word warn, on opening, that
    the file contains fields which may refer to other files."""
    lines = ["\\section*{Contents}"]
    for match in re.finditer(r"\\(section|subsection)\*\{", body):
        title, _ = braced(body, match.end() - 1)
        number, _, name = " ".join(title.split()).partition(" ")
        indent = "" if match.group(1) == "section" else "\\quad "
        # \mbox stops the LaTeX reader from treating the number as a list marker.
        lines.append(f"\\noindent {indent}\\mbox{{{number}}} {name}\\par")
    lines += ["\\noindent Acknowledgments\\par", "\\noindent References\\par"]
    return "\n".join(lines)


def build_driver():
    title, groups, ack, chapters = parse_main()
    authors = " \\and ".join(groups)
    body = build_body(chapters)
    return (
        "\\documentclass{article}\n"
        f"\\title{{{title}}}\n"
        f"\\author{{{authors}}}\n"
        "\\begin{document}\n\\maketitle\n\n"
        f"{contents_block(body)}\n\n"
        f"{body}\n\n"
        f"\\section*{{Acknowledgments}}\n{ack}\n\n"
        "\\section*{References}\n"
        "\\end{document}\n"
    )


def pandoc_executable():
    if (exe := shutil.which("pandoc")):
        return exe
    import pypandoc
    return pypandoc.get_pandoc_path()


def finalize(path):
    """A4 page, and no fields or external links for Word to refresh on opening."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Cm

    document = Document(path)
    for section in document.sections:
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.0)
        section.top_margin = section.bottom_margin = Cm(2.0)
    unwrap_external_links(document)
    document.save(path)


def unwrap_external_links(document):
    """Keep the visible address, drop the hyperlink, so nothing points outside."""
    from docx.oxml.ns import qn

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rid_attr = qn("r:id")
    parts = [document.part]
    for rel in document.part.rels.values():
        if rel.is_external:
            continue
        target = rel.target_part
        if (hasattr(target, "element")
                and str(target.partname).endswith(("footnotes.xml", "endnotes.xml", "comments.xml"))):
            parts.append(target)
    used = set()
    for part in parts:
        for link in part.element.findall(".//w:hyperlink", ns):
            rid = link.get(rid_attr)
            if rid is None or not part.rels[rid].is_external:
                continue
            parent = link.getparent()
            index = list(parent).index(link)
            for child in list(link):
                for style in child.findall(".//w:rStyle", ns):
                    if style.get(qn("w:val")) == "Hyperlink":
                        style.getparent().remove(style)
                parent.insert(index, child)
                index += 1
            parent.remove(link)
            used.add((part, rid))
    for part, rid in used:
        part.drop_rel(rid)
    drop_external_relationships(document.part)


def drop_external_relationships(part, seen=None):
    """Pandoc also parks unused DOI links in footnotes.xml.rels."""
    if seen is None:
        seen = set()
    if part in seen:
        return
    seen.add(part)
    internal = [rel.target_part for rel in part.rels.values() if not rel.is_external]
    for rid, rel in list(part.rels.items()):
        if rel.is_external:
            part.drop_rel(rid)
    for target in internal:
        if hasattr(target, "rels"):
            drop_external_relationships(target, seen)


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "cdr.tex"
        driver.write_text(build_driver(), encoding="utf-8")
        subprocess.run(
            [pandoc_executable(), str(driver), "-f", "latex", "-t", "docx",
             "-o", str(out), "--citeproc", "--bibliography", str(BIB),
             "--csl", str(CSL), "--resource-path", str(IMG)],
            check=True)
    finalize(out)
    print(f"Written {out}")


if __name__ == "__main__":
    main()
