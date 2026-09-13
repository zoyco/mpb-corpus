#!/usr/bin/env python3
"""Merge, split and check the MPB Corpus dataset.

Generative AI assistance
------------------------
This script was written with the assistance of generative AI (Claude, by
Anthropic) in September 2026. Its behaviour was verified by fault injection:
a corrupted copy of the dataset was produced for each failure mode below and
``check`` was confirmed to catch it.

The dataset exists in two layouts holding exactly the same rows:

    dataset_by_corpus/<corpus>/harmony.csv   one folder per corpus, each
                                             holding the three tables
    dataset_aggregated/harmony.csv           every corpus concatenated,
                                             in alphabetical order

``dataset_by_corpus/`` is the source of truth - it is what gets edited, and
one file per corpus and table keeps merge conflicts rare.
``dataset_aggregated/`` is generated from it and is what most analyses load.
This script keeps the two in step.

Commands
--------
merge          dataset_by_corpus/ -> dataset_aggregated/, the canonical
               direction. Run it after editing any per-corpus file.
split OUTDIR   dataset_aggregated/ -> OUTDIR, a derived copy. Refuses to
               write into dataset_by_corpus/.
check          compare the two layouts field by field and report how they
               differ, plus the format contract. Exit status 0 if clean,
               1 if anything is wrong, so CI can call it.

Usage
-----
Run from the repository root - the directory holding ``dataset_by_corpus/``::

    python scripts/mpb_corpus.py merge
    python scripts/mpb_corpus.py split ../staging
    python scripts/mpb_corpus.py check

The dataset is located relative to this file, not to the working directory, so
the commands work from anywhere; only the path you type to the script changes
with it.

Python 3.9 or newer, no packages to install.

A typical edit session::

    # fix a typo in dataset_by_corpus/<corpus>/harmony.csv, then
    python scripts/mpb_corpus.py merge
    python scripts/mpb_corpus.py check

``split`` is for the rarer direction - someone hands you a corrected aggregate
and you want it back in per-corpus form::

    python scripts/mpb_corpus.py split ../staging
    diff -r dataset_by_corpus ../staging      # inspect before trusting it
    # then move the files in by hand

The refusal to write into ``dataset_by_corpus/``, or anywhere under it, is
deliberate: a split writes only the corpora that appear in the aggregate, so a
stale aggregate would silently leave a dropped corpus behind, looking
untouched.

Format contract
---------------
Comma-delimited, UTF-8 **without BOM**, LF line endings, trailing newline, on
every CSV. Reading tolerates a BOM (Excel adds one); writing never emits one.
``check`` enforces all of it - Excel restores CRLF on save and that is the
single most common way these files get damaged.

The functions here are importable, and useful on their own::

    from mpb_corpus import read_csv, AGGREGATED
    header, rows = read_csv(AGGREGATED / "harmony.csv")

Standard library only, on purpose: this must still run years from now, when a
pinned scientific stack no longer resolves.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

#: The three dataset tables. Each exists once per corpus and once aggregated.
TABLES = ("contour_rhythm", "harmony", "note_function")

#: Expected header of each table, in order. A file whose header differs is a
#: failure, not something to reconcile - column order is part of the published
#: format.
SCHEMAS = {
    "contour_rhythm": ["corpus_id", "composition_id", "composition_name",
                       "word_index", "c_word", "r_word"],
    "harmony": ["corpus_id", "composition_id", "composition_name", "chord_index",
                "root", "bass", "chord_type", "chord_symbol",
                "functional_category", "key", "mode", "position"],
    "note_function": ["corpus_id", "composition_id", "composition_name", "mode",
                      "note_index", "scale_degree", "note_function"],
}

#: Repository paths, derived from this file's location rather than the working
#: directory, so every command behaves the same wherever it is run from.
ROOT = Path(__file__).resolve().parent.parent
BY_CORPUS = ROOT / "dataset_by_corpus"
AGGREGATED = ROOT / "dataset_aggregated"


def read_csv(path):
    """Read one CSV and return ``(header, rows)``.

    Every field comes back as a ``str``; nothing is coerced. That is on
    purpose - ``composition_id`` is written ``1``, not ``1.0``, and some
    ``r_word`` values are the literal string ``nan``, which any numeric
    conversion would turn into a missing value. (Loading with pandas needs
    ``keep_default_na=False`` for the same reason.)

    Decoded as ``utf-8-sig``, so a file that picked up a BOM in Excel still
    reads correctly and the BOM does not end up glued to ``corpus_id``.
    ``check`` reports the BOM separately; reading stays liberal.

    Args:
        path: Path to the CSV.

    Returns:
        A ``(header, rows)`` tuple: the first line as a list of column names,
        and the remaining lines as a list of lists of strings.

    Raises:
        IndexError: if the file is empty (it has no header line).

    Example::

        header, rows = read_csv(AGGREGATED / "harmony.csv")
        # header  -> SCHEMAS["harmony"]
        # rows[0] -> every field a string, the corpus_id first
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def write_csv(path, header, rows):
    """Write one CSV in the canonical format, creating parent folders.

    UTF-8 without BOM, LF line endings on every platform, trailing newline.
    Writing through this function is what makes the output byte-identical on
    Windows and Linux, so published checksums hold.

    An existing file is overwritten.

    Args:
        path: Destination path. Missing parent directories are created.
        header: Column names, written as the first line.
        rows: Sequence of rows, each a sequence of values.

    Example::

        write_csv(Path("staging") / corpus / "harmony.csv",
                  SCHEMAS["harmony"], rows)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def corpora():
    """Return the corpus names, alphabetically.

    One name per folder in ``dataset_by_corpus/``. Alphabetical order is the
    published row order of the aggregate, so both ``merge`` and ``check``
    depend on this being sorted.

    Returns:
        A sorted list of the folder names, one per corpus.
    """
    return sorted(p.name for p in BY_CORPUS.iterdir() if p.is_dir())


def rows_by_corpus(rows):
    """Group rows by ``corpus_id``, keeping the order they appear in.

    Args:
        rows: Rows whose first field is the ``corpus_id``.

    Returns:
        A dict mapping corpus name to its list of rows.
    """
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    return grouped


def compare_rows(expected, actual, label, where, fail):
    """Compare two lists of rows field by field and report how they differ.

    The two lists must be identical - same rows, same values, same order - for
    the layouts to be in step. When they are not, this says what changed
    rather than only that something did:

    * the first position where the rows differ, as a line number in `where`,
      with both versions printed;
    * rows present in one layout and not the other, counted, with an example;
    * rows that are all present on both sides but in a different order.

    A single edited field shows up as one row missing and one row extra, which
    the positional report pins to a line; that is why both are reported.

    Args:
        expected: Rows from ``dataset_by_corpus/``, the source of truth.
        actual: Rows from ``dataset_aggregated/``.
        label: Prefix identifying what is being compared - a table name for a
            whole-table comparison, ``<table> / <corpus>`` for one corpus.
        where: Path of the file whose numbering the reported line refers to.
            Both lists are in the same order, so one line number locates the
            difference in either; this names the file it is counted in.
        fail: Callback taking one message string, called once per problem.

    Returns:
        ``True`` if the two lists are identical.
    """
    if expected == actual:
        return True

    for i, (want, got) in enumerate(zip(expected, actual)):
        if want != got:
            fail(f"{label}: first difference at line {i + 2} of {where}\n"
                 f"       dataset_by_corpus/:  {','.join(want)}\n"
                 f"       dataset_aggregated/: {','.join(got)}")
            break

    missing = Counter(map(tuple, expected)) - Counter(map(tuple, actual))
    extra = Counter(map(tuple, actual)) - Counter(map(tuple, expected))
    if missing:
        example = ",".join(next(iter(missing)))
        fail(f"{label}: {sum(missing.values())} row(s) in dataset_by_corpus/ "
             f"are absent from dataset_aggregated/, e.g. {example}")
    if extra:
        example = ",".join(next(iter(extra)))
        fail(f"{label}: {sum(extra.values())} row(s) in dataset_aggregated/ "
             f"are absent from dataset_by_corpus/, e.g. {example}")
    if not missing and not extra:
        fail(f"{label}: both layouts hold the same {len(expected)} rows, "
             f"but in a different order")
    return False


def merge():
    """Rebuild ``dataset_aggregated/`` from ``dataset_by_corpus/``.

    For each table, concatenates the per-corpus files in alphabetical order of
    corpus and writes the result, overwriting whatever was there. The header
    written is the one from :data:`SCHEMAS`, not the one read, so a file with a
    damaged header cannot corrupt the aggregate silently - run ``check`` to
    catch that case.

    Prints a row count per table. Run ``check`` afterwards to confirm.

    Example::

        python scripts/mpb_corpus.py merge
        # one line per table, each naming the number of rows written and the
        # number of corpora they came from:
        # harmony: <rows> rows from <corpora> corpora
    """
    for table in TABLES:
        rows = []
        for corpus in corpora():
            _, corpus_rows = read_csv(BY_CORPUS / corpus / f"{table}.csv")
            rows.extend(corpus_rows)
        write_csv(AGGREGATED / f"{table}.csv", SCHEMAS[table], rows)
        print(f"{table}: {len(rows)} rows from {len(corpora())} corpora")


def split(out_dir):
    """Split ``dataset_aggregated/`` into per-corpus folders under `out_dir`.

    Rows are grouped by ``corpus_id`` (the first column) and written to
    ``out_dir/<corpus_id>/<table>.csv``, keeping the order they appear in.
    Existing files at those paths are overwritten; files already in `out_dir`
    that this split does not produce are left alone.

    This is the derived direction. ``dataset_by_corpus/`` is refused as a
    destination, and so is anything inside it: only corpora present in the
    aggregate get written, so a stale aggregate would leave a dropped corpus
    sitting there looking current. Split to a staging directory, inspect it,
    and move the files in by hand.

    Args:
        out_dir: Destination directory, created if needed.

    Raises:
        SystemExit: if `out_dir` is ``dataset_by_corpus/`` or a path under it.

    Example::

        python scripts/mpb_corpus.py split ../staging
        # one line per table:
        # harmony: <rows> rows -> <corpora> corpora
    """
    out_dir = Path(out_dir).resolve()
    source = BY_CORPUS.resolve()
    if out_dir == source or source in out_dir.parents:
        sys.exit(f"refusing to write into {BY_CORPUS} (the source of truth); "
                 f"choose another directory")
    for table in TABLES:
        header, rows = read_csv(AGGREGATED / f"{table}.csv")
        by_corpus = {}
        for row in rows:
            by_corpus.setdefault(row[0], []).append(row)
        for corpus, corpus_rows in by_corpus.items():
            write_csv(out_dir / corpus / f"{table}.csv", header, corpus_rows)
        print(f"{table}: {len(rows)} rows -> {len(by_corpus)} corpora")


def check():
    """Verify that the two layouts hold identical data, and report how not.

    The comparison is by content, field by field, not by row counts or
    checksums. For each table it checks

    * **structure** - no loose files outside a corpus folder; every corpus
      folder has the file; no corpus appears in the aggregate without a
      folder of its own;
    * **shape** - the expected header, in the expected column order, and no
      ragged rows, on both sides;
    * **content, corpus by corpus** - the rows the aggregate carries for a
      given ``corpus_id`` are exactly that corpus's file, in the same order;
    * **content, whole table** - the aggregate as a whole is the per-corpus
      files concatenated alphabetically, which catches corpus blocks that are
      out of order or interleaved even when each block is itself correct;
    * **provenance** - a per-corpus file holds only its own ``corpus_id``;
    * **format** - UTF-8 without BOM, LF, trailing newline, on every file
      (see :func:`check_format`).

    Differences are diagnosed rather than merely flagged: see
    :func:`compare_rows`. The whole-table comparison runs only once every
    corpus matches, so a real difference is reported where it happened
    instead of twice over.

    All of this is data validation. It does not validate the music: index
    columns running 1..n, ``composition_name`` agreeing across tables, and the
    tables covering the same compositions are outside its scope.

    Problems are printed as they are found, prefixed ``FAIL``, followed by a
    count. Checking continues after a failure, so one run reports everything.

    Returns:
        The number of problems found; ``0`` means the two layouts are
        identical in content. The command-line entry point turns this into
        exit status 0 or 1.

    Example, when the layouts agree - one line per table, then the count::

        python scripts/mpb_corpus.py check
        # harmony: OK, <rows> identical rows across <corpora> corpora
        #
        # 0 problem(s)

    and when one field has been edited on one side only, the same difference
    reported three ways - where it is, and what is missing from each side::

        # FAIL harmony / <corpus>: first difference at line 276 of
        #                          dataset_by_corpus/<corpus>/harmony.csv
        #        dataset_by_corpus/:  <corpus>,9,Song name,1,9,9,V0,*,I,...
        #        dataset_aggregated/: <corpus>,9,Song name,1,7,9,V0,*,I,...
        # FAIL harmony / <corpus>: 1 row(s) in dataset_by_corpus/ are absent
        #                          from dataset_aggregated/, e.g. ...
        # FAIL harmony / <corpus>: 1 row(s) in dataset_aggregated/ are absent
        #                          from dataset_by_corpus/, e.g. ...
        #
        # 3 problem(s)
    """
    problems = []

    def fail(msg):
        problems.append(msg)
        print(f"FAIL {msg}")

    loose = sorted(p.name for p in BY_CORPUS.iterdir() if p.is_file())
    if loose:
        fail(f"dataset_by_corpus/ holds loose file(s) {loose}; every CSV "
             f"belongs inside a corpus folder")

    for table in TABLES:
        # --- read dataset_by_corpus/ ------------------------------------
        per_corpus = {}
        for corpus in corpora():
            path = BY_CORPUS / corpus / f"{table}.csv"
            if not path.exists():
                fail(f"{corpus}/{table}.csv is missing")
                continue
            check_format(path, fail)
            header, rows = read_csv(path)
            if header != SCHEMAS[table]:
                fail(f"{corpus}/{table}.csv header is {header}")
            if any(len(row) != len(SCHEMAS[table]) for row in rows):
                fail(f"{corpus}/{table}.csv has rows of the wrong width")
            foreign = sorted({row[0] for row in rows} - {corpus})
            if foreign:
                fail(f"{corpus}/{table}.csv holds rows of corpus {foreign}")
            per_corpus[corpus] = rows

        # --- read dataset_aggregated/ -----------------------------------
        path = AGGREGATED / f"{table}.csv"
        if not path.exists():
            fail(f"dataset_aggregated/{table}.csv is missing; run merge")
            continue
        check_format(path, fail)
        header, agg_rows = read_csv(path)
        if header != SCHEMAS[table]:
            fail(f"dataset_aggregated/{table}.csv header is {header}")
        if any(len(row) != len(SCHEMAS[table]) for row in agg_rows):
            fail(f"dataset_aggregated/{table}.csv has rows of the wrong width")

        # --- content, corpus by corpus ----------------------------------
        aggregated = rows_by_corpus(agg_rows)
        orphans = sorted(set(aggregated) - set(per_corpus))
        for corpus in orphans:
            fail(f"{table}: dataset_aggregated/ carries "
                 f"{len(aggregated[corpus])} row(s) of corpus {corpus!r}, "
                 f"which has no folder in dataset_by_corpus/")
        matched = [compare_rows(rows, aggregated.get(corpus, []),
                                f"{table} / {corpus}",
                                f"dataset_by_corpus/{corpus}/{table}.csv", fail)
                   for corpus, rows in sorted(per_corpus.items())]

        # --- content, whole table ---------------------------------------
        # Only worth asking once every corpus matches: what is left to catch
        # is the arrangement of the blocks, not the rows inside them.
        if all(matched) and not orphans:
            expected = [row for _, rows in sorted(per_corpus.items())
                        for row in rows]
            if compare_rows(expected, agg_rows, table,
                            f"dataset_aggregated/{table}.csv", fail):
                print(f"{table}: OK, {len(agg_rows)} identical rows "
                      f"across {len(per_corpus)} corpora")

    print(f"\n{len(problems)} problem(s)")
    return len(problems)


def check_format(path, fail):
    """Check one file against the format contract.

    Reports a UTF-8 BOM, CRLF line endings, or a missing trailing newline.
    All three are what a round trip through Excel or a Windows editor leaves
    behind; none changes the data, but each breaks published checksums and
    some readers.

    Args:
        path: File to check, inside :data:`ROOT`.
        fail: Callback taking one message string, called once per problem.
    """
    raw = path.read_bytes()
    name = path.relative_to(ROOT).as_posix()   # forward slashes on every OS
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"{name} has a UTF-8 BOM")
    if b"\r\n" in raw:
        fail(f"{name} has CRLF line endings")
    if raw and not raw.endswith(b"\n"):
        fail(f"{name} has no trailing newline")


if __name__ == "__main__":
    # Run as a script: dispatch on the command word. Imported instead, this
    # block is skipped and the functions above are available as a library.
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "merge":
        merge()
    elif command == "split" and len(sys.argv) == 3:
        split(sys.argv[2])
    elif command == "check":
        # Exit status, so CI and shell `&&` chains can act on the result.
        sys.exit(1 if check() else 0)
    else:
        # Anything else - no command, a typo, or `split` without a destination
        # - prints the module docstring and exits non-zero.
        sys.exit(__doc__)
