# Scripts

Two command-line tools, both **standard library only** — no installation, no
environment, nothing to pin. Python 3.9 or newer and nothing else, so they
should still run long after a pinned scientific stack has stopped resolving.

Run them from the repository root — the directory holding `dataset_by_corpus/`:

```
python scripts/mpb_corpus.py check
python scripts/metadata_pipeline.py build
```

Each script locates the dataset relative to its own position, so the working
directory does not matter; only the path you type to reach the script does.

Both were written with the assistance of generative AI, and each file says so at
the top. `metadata_pipeline.py` is based on the pipeline in
[stefan-balke/mpb-corpus](https://github.com/stefan-balke/mpb-corpus).

---

## `mpb_corpus.py` — the dataset

| command | what it does |
|---|---|
| `merge` | rebuild `dataset_aggregated/` from `dataset_by_corpus/` |
| `split OUTDIR` | write `dataset_aggregated/` back out as per-corpus folders, into a directory you name |
| `check` | compare the two layouts field by field; exit 0 if clean, 1 if not |

`dataset_by_corpus/` is the source of truth. After editing any file there:

```
python scripts/mpb_corpus.py merge
python scripts/mpb_corpus.py check
```

`check` compares the layouts by content and reports *how* they differ rather
than only that they do. It also enforces the format contract — comma-delimited,
UTF-8 without BOM, LF line endings, trailing newline — which matters because
saving a CSV from a spreadsheet restores CRLF, breaking published checksums
without changing a single value. Its exit status makes it usable from CI.

`split` refuses to write into `dataset_by_corpus/`, or anywhere beneath it. It
writes only the corpora present in the aggregate, so a stale aggregate could
silently leave a dropped corpus behind, looking untouched. Split into a staging
directory, inspect it, and move the files in by hand.

---

## `metadata_pipeline.py` — the external identifiers

| command | what it does | network |
|---|---|---|
| `build` | refresh composition identity from `dataset_by_corpus/` | no |
| `spotify` | fetch the corpus playlists and match compositions by title | yes |
| `isrc` | fetch each matched track's ISRC from the Spotify Web API | yes, **needs credentials** |
| `mbisrc` | look up MusicBrainz recording and work ids by ISRC | yes |

That is also the order they depend on one another in, and each refuses to run
if its input is missing. `build` is offline and leaves every external identifier
untouched. The other three rewrite `metadata/compositions.csv` when they
finish — nothing in `metadata/` should be edited by hand.

### Credentials

`isrc` is the only command needing any. Register an application at
https://developer.spotify.com/dashboard and pass the credentials through the
environment, never a file:

```
PowerShell  $env:SPOTIFY_CLIENT_ID='...'; $env:SPOTIFY_CLIENT_SECRET='...'
bash        export SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...
```

No user login is involved; this is the client-credentials flow, which reads
public catalogue data only.

### Running time

`spotify` takes seconds, `isrc` about four minutes, `mbisrc` about fifteen —
longer in practice, since MusicBrainz returns HTTP 503 freely and the retry
backoff waits it out. `mbisrc` caches every answer, so an interrupted run
resumes where it stopped; delete `metadata/musicbrainz_isrc_lookups.csv` to
force a fresh lookup.

### Reading the results

See [`../metadata/README.md`](../metadata/README.md), which documents every
column and how far each can be trusted.
