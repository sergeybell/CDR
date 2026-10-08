"""Check the CDR bibliography against REVTeX and INSPIRE HEP.

REVTeX formats whatever BibTeX it is given, and this project takes those entries
from INSPIRE unchanged (cite, then BibTeX, same key). The check has two parts:

- REVTeX: ``\\bibliography`` is set, ``\\bibliographystyle`` is not, citations
  use natbib commands, every key resolves, and a local entry still has the
  fields BibTeX needs.
- INSPIRE: each entry matches the BibTeX INSPIRE serves for that texkey.
  A work that is genuinely absent is allowed only with a ``% Not in INSPIRE``
  comment immediately above the entry.

Usage: python support/check-references/check_references.py [--offline]
"""

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LATEX = ROOT / "latex"

REVTEX_TYPES = {
    "article", "book", "booklet", "conference", "inbook", "incollection",
    "inproceedings", "manual", "mastersthesis", "misc", "phdthesis",
    "proceedings", "techreport", "unpublished",
}
CITE_COMMANDS = {
    "cite", "onlinecite", "citet", "citep", "citealt", "citealp",
    "citeauthor", "citeyear", "citeyearpar", "nocite",
}
USER_AGENT = "CDR-check-references"


@dataclass
class Entry:
    type: str
    key: str
    fields: list[tuple[str, str]]
    line: int
    local_only: bool
    source: str

    def value(self, name):
        for field_name, value in self.fields:
            if field_name.lower() == name:
                return plain(value)
        return None


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)


def plain(value):
    """Drop the quote delimiters. Braces stay, they protect capitalization."""
    value = value.strip()
    if len(value) >= 2 and value[0] == "\"" and value[-1] == "\"":
        value = value[1:-1]
    return value.strip()


def norm(value):
    return re.sub(r"\s+", " ", value).strip()


def read_value(text, start):
    """Return the raw BibTeX value, delimiters included, and the index after it."""
    i = start
    while text[i].isspace():
        i += 1
    if text[i] == "{":
        depth = 0
        begin = i
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[begin:i + 1], i + 1
            i += 1
        raise ValueError("unbalanced braces")
    if text[i] == "\"":
        end = text.index("\"", i + 1)
        return text[i:end + 1], end + 1
    end = i
    while end < len(text) and text[end] not in ",}":
        end += 1
    return text[i:end].strip(), end


def preceding_note(text, start):
    notes = []
    pos = start
    while pos > 0:
        line_start = text.rfind("\n", 0, pos - 1) + 1
        line = text[line_start:pos].strip()
        if line.startswith("%"):
            notes.append(line)
        elif line:
            break
        pos = line_start
    return "\n".join(reversed(notes))


def parse_bib(text):
    entries = []
    for match in re.finditer(r"@(\w+)\s*\{", text):
        kind = match.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        i = match.end()
        key_end = i
        while text[key_end] not in ",}":
            key_end += 1
        key = text[i:key_end].strip()
        i = key_end + (text[key_end] == ",")
        fields = []
        while True:
            while text[i].isspace():
                i += 1
            if text[i] == "}":
                break
            name_end = text.find("=", i)
            name = text[i:name_end].strip()
            value, i = read_value(text, name_end + 1)
            fields.append((name, value))
            while text[i].isspace():
                i += 1
            if text[i] == ",":
                i += 1
        note = preceding_note(text, match.start())
        entries.append(Entry(
            type=kind,
            key=key,
            fields=fields,
            line=text.count("\n", 0, match.start()) + 1,
            local_only="not in inspire" in note.lower(),
            source=text[match.start():i + 1].strip(),
        ))
    return entries


def strip_comments(text):
    return re.sub(r"(?<!\\)%.*", "", text)


def citations(latex):
    found = []
    paths = [latex / "main.tex", *sorted((latex / "chapters").glob("*.tex"))]
    command = re.compile(
        r"\\([A-Za-z]+)\s*(?:\[[^\]]*\]){0,2}\s*\{([^{}]*)\}"
    )
    for path in paths:
        text = strip_comments(path.read_text(encoding="utf-8"))
        for match in command.finditer(text):
            name = match.group(1)
            if not name.lower().startswith("cite"):
                continue
            line = text.count("\n", 0, match.start()) + 1
            keys = [key.strip() for key in match.group(2).split(",") if key.strip()]
            found.append((path.relative_to(latex).as_posix(), line, name, keys))
    return found


def check_revtex(report, main, entries, cites):
    if re.search(r"\\bibliographystyle\b", main):
        report.error("main.tex задаёт \\bibliographystyle; в REVTeX стиль выбирает класс")
    if not re.search(r"\\bibliography\s*\{", main):
        report.error("main.tex не содержит \\bibliography")

    known = {}
    for entry in entries:
        if entry.key in known:
            report.error(f"{entry.key}: ключ повторяется, первое вхождение на строке {known[entry.key]}")
        known[entry.key] = entry.line
        if entry.type not in REVTEX_TYPES:
            report.error(f"{entry.key}: тип @{entry.type} REVTeX не оформляет")
        if entry.local_only:
            check_local_fields(report, entry)

    cited = set()
    for path, line, command, keys in cites:
        if command.lower() not in CITE_COMMANDS:
            report.error(f"{path}:{line}: \\{command} не входит в набор команд REVTeX/natbib")
        if not keys:
            report.error(f"{path}:{line}: пустая команда \\{command}")
        for key in keys:
            cited.add(key)
            if key not in known:
                report.error(f"{path}:{line}: нет записи BibTeX для {key}")
    for entry in entries:
        if entry.key not in cited:
            report.warn(f"{entry.key}: запись есть в .bib, но нигде не цитируется")


def check_local_fields(report, entry):
    names = {name.lower() for name, _ in entry.fields}
    where = f"{entry.key} (нет в INSPIRE)"
    if "title" not in names:
        report.error(f"{where}: нет title")
    if "author" not in names and "collaboration" not in names:
        report.error(f"{where}: нет author")
    if "year" not in names:
        report.error(f"{where}: нет year, REVTeX оставит пустой год")
    if entry.type == "article" and "journal" not in names:
        report.error(f"{where}: у @article нет journal")
    if entry.type == "inproceedings" and "booktitle" not in names:
        report.error(f"{where}: у @inproceedings нет booktitle")


def fetch_bibtex(query):
    url = "https://inspirehep.net/api/literature?" + urllib.parse.urlencode({
        "q": query, "format": "bibtex", "size": "100",
    })
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/x-bibtex",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read().decode("utf-8").strip()
    if data.startswith(("{", "[")):
        raise RuntimeError(data[:300])
    return data


def inspire_by_texkey(keys):
    found = {}
    for start in range(0, len(keys), 15):
        chunk = keys[start:start + 15]
        query = " or ".join(f"texkeys:{key}" for key in chunk)
        for entry in parse_bib(fetch_bibtex(query)):
            found[entry.key] = entry
    return found


def inspire_by_doi(doi):
    entries = parse_bib(fetch_bibtex(f'doi:"{doi}"'))
    return entries[0] if entries else None


def compare(report, local, official):
    local_fields = {name.lower(): (name, norm(plain(value))) for name, value in local.fields}
    official_fields = {name.lower(): (name, norm(plain(value))) for name, value in official.fields}
    diffs = []
    if local.type != official.type:
        diffs.append(f"тип @{local.type}, в INSPIRE @{official.type}")
    for name in official_fields.keys() - local_fields.keys():
        shown, value = official_fields[name]
        diffs.append(f"нет поля {shown} = {value}")
    for name in local_fields.keys() - official_fields.keys():
        shown, value = local_fields[name]
        diffs.append(f"лишнее поле {shown} = {value}")
    for name in official_fields.keys() & local_fields.keys():
        if local_fields[name][1] != official_fields[name][1]:
            diffs.append(
                f"поле {official_fields[name][0]}:\n"
                f"    у нас:    {local_fields[name][1]}\n"
                f"    INSPIRE:  {official_fields[name][1]}"
            )
    order_local = [name.lower() for name, _ in local.fields]
    order_official = [name.lower() for name, _ in official.fields]
    if not diffs and order_local != order_official:
        report.warn(f"{local.key}: значения совпали, но порядок полей не как в INSPIRE")
        return
    if diffs:
        rendered = "\n  ".join(diffs)
        report.error(
            f"{local.key}: не совпадает с BibTeX INSPIRE HEP\n  {rendered}\n"
            f"  эталон:\n{indent(official.source)}"
        )


def indent(text):
    return "\n".join(f"    {line}" for line in text.splitlines())


def check_inspire(report, entries):
    lookup = [entry for entry in entries if not entry.local_only]
    official = inspire_by_texkey([entry.key for entry in lookup])
    for entry in entries:
        if entry.local_only:
            doi = entry.value("doi")
            if not doi:
                continue
            found = inspire_by_doi(doi)
            if found:
                report.error(
                    f"{entry.key}: помечена как отсутствующая в INSPIRE, "
                    f"но по DOI это {found.key}\n  эталон:\n{indent(found.source)}"
                )
            continue
        found = official.get(entry.key)
        if found is None and (doi := entry.value("doi")):
            found = inspire_by_doi(doi)
            if found and found.key != entry.key:
                report.error(
                    f"{entry.key}: в INSPIRE эта работа записана как {found.key}\n"
                    f"  эталон:\n{indent(found.source)}"
                )
                continue
        if found is None:
            report.error(
                f"{entry.key}: нет в INSPIRE HEP. Если работы там действительно нет, "
                "поставьте над записью комментарий % Not in INSPIRE"
            )
            continue
        compare(report, entry, found)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Проверка ссылок CDR: REVTeX и INSPIRE HEP")
    parser.add_argument("--offline", action="store_true", help="только проверки REVTeX, без запроса к INSPIRE")
    args = parser.parse_args()

    main_text = (LATEX / "main.tex").read_text(encoding="utf-8")
    bib_name = re.search(r"\\bibliography\s*\{([^}]+)\}", main_text).group(1)
    bib_path = LATEX / f"{bib_name}.bib"
    entries = parse_bib(bib_path.read_text(encoding="utf-8"))
    cites = citations(LATEX)
    report = Report()
    check_revtex(report, main_text, entries, cites)

    if args.offline:
        print("INSPIRE HEP не проверялся (--offline).")
    else:
        try:
            check_inspire(report, entries)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            report.error(f"INSPIRE HEP недоступен: {exc}")

    for message in report.errors:
        print(f"Ошибка: {message}\n")
    for message in report.warnings:
        print(f"Замечание: {message}")
    print(f"Записей: {len(entries)}. Ошибок: {len(report.errors)}. Замечаний: {len(report.warnings)}.")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
