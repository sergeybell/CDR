# CDR — вклад группы EDM (INR RAS) в SPRINT@NICA

Conceptual Design Report по поиску электрического дипольного момента (EDM)
лёгких ядер и связанных экспериментам на комплексе NICA. Текст готовит группа
из ИЯИ РАН (с соавторами из MIPT, MEPhI, ИТФ, ОИЯИ) в формате, удобном для
включения в общий CDR коллаборации.

Документ собран в **REVTeX 4.2** (стиль APS): так же оформляют статьи для
Physical Review, поэтому библиография, цитирования и вёрстка совместимы с тем,
что принято в HEP/accelerator community. Общий `.bib` сверяется с
[INSPIRE HEP](https://inspirehep.net).

## Структура репозитория

### `authors/`
Исходники от авторов (Word, PDF, черновики рисунков). Каждая папка — материалы
одного человека; их не правят «на месте», а переносят в `latex/`.

### `latex/` — единственная сборка CDR
То, что можно отправить коллегам и собрать одной командой.

| Путь | Содержимое |
|------|------------|
| `main.tex` | титул, авторы, подключение глав |
| `chapters/` | текст по разделам |
| `img/` | все рисунки |
| `bib/references.bib` | единый список литературы |

**Главы**

1. Introduction — постановка задачи и варианты на NICA  
2. QFS — идея quasi-frozen spin  
3. NICA bypass — коллайдер с байпасами и Wien-фильтрами  
4. Nuclotron — модернизация Нуклотрона  
5. Specialized ring — выделенные FS-кольца на площадке ОИЯИ  
6. Spinor — матричное / спинорное описание и FDM  
7. Axion — режим поиска аксионов  

Сборка из каталога `latex/`:

```bash
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

Готовый `latex/main.pdf` лежит в репозитории — его можно скачать с GitHub без локальной сборки.

### `support/` — вспомогательные скрипты

| Скрипт | Зачем |
|--------|--------|
| `check-revtex/` | не сломать соглашения REVTeX/APS (класс, пакеты, `\bibliography`) |
| `check-references/` | все `\cite` резолвятся; записи из INSPIRE совпадают с экспортом |
| `check-figures/` | у рисунков есть `\label`, на них есть `\ref`, файлы лежат в `img/` |
| `tex-to-docx/` | выгрузка в Word (`authors/ЮВСеничев/CDR_contribution_3.docx`) для правок вне LaTeX |

Почему важен REVTeX: один стиль с журнальными статьями группы, предсказуемая
библиография (natbib + `apsrev`), меньше сюрпризов при слиянии с общим CDR.
Ключи работ из INSPIRE берём как в BibTeX-экспорте; если работы там нет —
помечаем `% Not in INSPIRE` и даём понятный локальный ключ.

```bash
python support/check-revtex/check_revtex.py
python support/check-references/check_references.py
python support/check-figures/check_figures.py
python support/tex-to-docx/build_docx.py
```
