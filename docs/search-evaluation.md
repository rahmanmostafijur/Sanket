# Search evaluation

A small harness to measure retrieval quality against labelled queries. It
measures; it does not tune anything. Nothing in the repository has been tuned
against it, and the example data below is synthetic.

**About 100 labelled query and job pairs are needed before tuning anything** (the
RRF `k`, the list weights, `HNSW_EF_SEARCH`, the text search configuration, the
embedded document). With a handful of queries one flipped judgement moves every
metric, so the numbers are for checking that the harness and the search work, not
for choosing settings.

## Labelled data format

A JSONL file, one JSON object per line, blank lines ignored:

```json
{"query": "python backend engineer", "relevant": [{"job_ref": "fp1:8e13...", "grade": 3}, {"job_ref": "fp1:d8cc...", "grade": 2}], "notes": "optional"}
```

| Field | Rule |
|---|---|
| `query` | 1 to 200 characters after trimming; must be unique in the file (ignoring case). |
| `relevant` | List of `{job_ref, grade}`; may be empty. A job not listed is not relevant. |
| `job_ref` | The job's fingerprint, `fp1:` followed by 64 lowercase hex digits. |
| `grade` | 1 somewhat relevant, 2 relevant, 3 highly relevant. |
| `notes` | Optional text, up to 1000 characters. |

Loading is strict: an unknown key, a bad grade or reference, a repeated reference
or a repeated query is an error naming the file and the line.

**Why fingerprints and not job ids.** Job ids are assigned by each database and
differ between the local database, the test database and production. The
fingerprint (`job.fingerprint`, ADR 0002) is computed from the job's company,
title and location, so it names the same job wherever it is canonicalised, and a
labelled file survives a database rebuild. The limit is that if the company,
title or location of a job changes, its fingerprint changes and the label no
longer finds it (the harness reports such references as missing).

### Finding fingerprints to label

```bash
python -m sanket.search.evaluate --find "python backend"
```

lists up to 15 jobs matching the text (full text only, no API key needed) with
their fingerprints, title, company and location. Copy the fingerprint into the
file with a grade. Judge relevance for the query as a job seeker typing it would;
look at jobs the system did not return too, not only at what it ranks first.

### The example file

`backend/eval/queries.example.jsonl` has eight queries (English, Swedish and
Bengali, and one with no relevant job) over a small invented corpus defined in
`backend/tests/eval_corpus.py`. The tests build that corpus in the test database,
index it with the fake embedding client and run the harness on the file, so the
references are real fingerprints of those synthetic jobs. They do not exist in
any real database; copy the format, not the contents.

## Running it

From `backend/`:

```bash
python -m sanket.search.evaluate --queries eval/queries.example.jsonl --k 10
python -m sanket.search.evaluate --queries my-queries.jsonl --k 10 --mode all --json report.json
```

| Option | Meaning |
|---|---|
| `--queries` | The labelled file. |
| `--k` | Cut-off for every metric, default 10; at most `SEARCH_CANDIDATES`. |
| `--mode` | `hybrid` (default), `text`, `vector` or `all` to compare the three side by side. |
| `--json` | Also write the full report (aggregates, per-query metrics, ranked fingerprints). |
| `--find TEXT` | List matching jobs with fingerprints and exit. |

It reads the settings like the other command line tools: it queries the database
in `DATABASE_URL` (shown without credentials at the top of the report), so point
it at the database that holds the jobs you labelled. It calls the service layer
directly, the same retrieval as the API with no filters. Hybrid and vector runs
make one real embedding call per distinct query when `GEMINI_API_KEY` is set (the
vectors are cached across modes), and refuse to run without a key; `--mode text`
needs none. The exit code is 1 if an embedding failed during a vector or hybrid
run, because those numbers would be missing the vector part (marked `!` in the
table).

## Reading the output

One row per query and one block of columns per mode: `R@k` (recall), `P@k`
(precision), `RR` (reciprocal rank) and `nDCG`, then a mean row over the scored
queries.

- **Recall@k**: relevant jobs in the top k divided by all relevant jobs.
- **Precision@k**: relevant jobs in the top k divided by k (always k, so a short
  result list is penalised for the empty positions).
- **MRR**: the mean over queries of 1 / rank of the first relevant job in the
  top k (0 if none). Shown as `RR` per query and as `MRR` in the summary lines.
- **nDCG@k**: graded relevance, gain `2^grade - 1`, discount `1 / log2(rank + 1)`,
  divided by the same sum for the ideal order, so 1.0 means the best possible
  ranking of the labelled jobs.
- A job that appears twice in a ranking counts once, at its first position.
- A query with no relevant jobs has no defined metrics. It is left out of the
  means and counted as excluded in the summary, rather than scored as 0 or 1.
- Labelled jobs that are not in the database are counted as relevant jobs that
  were not retrieved and reported in a warning.

## What this does not do

It does not tune, pick thresholds or fail on a score. It does not evaluate
filters, paging or degraded mode (the API tests cover those). Remote OK jobs have
no embedding (ADR 0003), so a vector-only run can never find them; compare modes
with that in mind.
