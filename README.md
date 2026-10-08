# CDR
CDR(Conceptual design report) of EDM group

- `authors/` — original materials from each author (docx, pdf), one folder per author (`author1/`, `author2/`, ...), figures in `authors/<author>/figs/`.
- `latex/` — LaTeX source of this CDR contribution, REVTeX 4.2 (`preprint`, single column): `main.tex`, one file per chapter in `latex/chapters/`, figures in `latex/img/`, references in `latex/bib/references.bib`. The class selects the bibliography style; do not set `\bibliographystyle` by hand.

Build in `latex/`: `pdflatex main && bibtex main && pdflatex main && pdflatex main`.

Take BibTeX entries from [INSPIRE HEP](https://inspirehep.net) ("cite" → BibTeX) and keep their keys unchanged.
