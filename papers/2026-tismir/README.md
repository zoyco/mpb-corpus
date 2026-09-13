# The MPB Corpus — TISMIR 2026

Companion code for:

> "The MPB Corpus: A Dataset of Melody, Rhythm, Harmony, and Melody-Harmony Relationships in Brazilian Popular Music" — INSERT CITATION

`analysis.ipynb` computes every metric proposed in the paper and reproduces every figure and table in it. All of them are discussed in the text.

## Notebook content

It is organised in three parts.

**Functions** — reference implementations of the three metrics the paper
proposes, plus the conversions and plots they rely on:

- the compensated intervallic economy index (CIEI)
- the countermetricity index (CMI)
- the melodic anchoring index (MAI)
- the NF-web plot
- converters between the corpus encodings and more familiar notations (c-letters to Parsons Code and to Dowling contour notation, r-words to a 12-dimensional attack-point vector, genealogical chord notation to pitch classes)
- the $R$ statistic and its hypothesis test

**Exploratory data analysis** — the figures and tables of the paper, grouped by musical dimension: melodic rhythm, melodic contour, harmony, and note functions.

**Examples** — worked demonstrations of each converter.

## Running it

The environment is pinned here, in this folder, rather than at the repository
root: a published result should stay reproducible as later work moves on to
newer versions of pandas and the rest. With [uv](https://docs.astral.sh/uv/)
installed and the repository cloned:

```
cd papers/2026-tismir
uv sync                       # build the environment from uv.lock
uv run jupyter lab            # open the notebook in it
```

`uv sync` installs the exact package versions recorded in `uv.lock` — 126 of
them — and the Python version recorded in `.python-version`, downloading that
interpreter if it is not already present. Nothing else is needed, and the
result is the same on Linux, macOS and Windows.

| file | purpose |
|---|---|
| `analysis.ipynb` | the notebook |
| `pyproject.toml` | the six direct dependencies |
| `uv.lock` | every version pinned, with hashes — this is what makes it reproducible |
| `.python-version` | the interpreter version |

`uv sync` creates a `.venv/` folder of roughly 460 MB. It is generated, listed
in `.gitignore`, and safe to delete at any time; `uv sync` rebuilds it. If this
repository lives inside a synchronised folder such as OneDrive or Dropbox, put
the environment elsewhere so the sync client does not try to copy twenty
thousand files:

```
UV_PROJECT_ENVIRONMENT=/some/path/outside/the/synced/folder uv sync
```

### One cell needs more than uv can install

The r-word visualisation uses [abjad](https://abjad.github.io/), which renders
notation through **LilyPond**. LilyPond is a separate program rather than a
Python package, so `uv sync` does not install it; fetch it from
[lilypond.org](https://lilypond.org/) if you want that cell to run. Every other
cell works without it.

## Which corpus version the results come from

The notebook reads the dataset from the repository it sits in:

```python
DATA = "../../dataset_aggregated"
DOCS = "../../documentation"
```

That is convenient while the paper is being written, and wrong for an archived
version — the corpus will grow, and figures regenerated years from now would no
longer be the published ones. For the archived release, pin those paths to the
released tag instead, as the comment in the first code cell describes:

```python
DATA = ("https://raw.githubusercontent.com/ProjetoMPB/mpb-corpus"
        "/v1.0.0/dataset_aggregated")
```

**The dataset version behind the published figures is not yet recorded.** It
should be stated here — git tag and Zenodo DOI — before this folder is
archived.

## A note on loading the data

`contour_rhythm.csv` must be read with `keep_default_na=False`. Four r-words
are the literal string `nan` (in Chico Buarque's *Acorda amor*, Gilberto Gil's
*Rebento*, Tom Jobim's *Bebel* and Ivan Lins's *Leva e traz*), and five c-words
are empty, marking a segment of a single syllable (Chico Buarque's *Calice*,
Gilberto Gil's *Drao*, Tom Jobim's *Modinha* twice, and Milton Nascimento's *Os
povos*). None of these is a missing value, and pandas silently converts all of
them unless that option is given.
