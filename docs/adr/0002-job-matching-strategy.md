# 0002: Matching postings to canonical jobs

Status: accepted

## Context

`posting` holds one row per `(source, source_id)`. The same real job often
appears in several sources (an aggregator and the employer's own board) or is
posted again under a new id. Search, matching and the feed should show one
entry per real job, so postings have to be grouped under a canonical `job`.

Raw data (`posting`), derived data (`posting_extraction`) and the canonical
entity (`job`) stay in separate tables. Other tables added later (embeddings,
matches) will refer to `job.id`, so job ids must stay stable.

The grouping has to be deterministic, cheap to run on every ingest, safe to
repeat, and honest about its mistakes: a wrong merge hides a real job, a
missed merge only shows a duplicate.

## Options

1. **Exact fingerprint on normalised fields.** Hash the normalised company,
   title and location. Deterministic, explainable, indexable (a unique column),
   no model or external call. It misses near-duplicates ("Sr. Engineer" and
   "Senior Software Engineer") and can merge two genuinely different jobs that
   share a title, company and location (for example two openings for the same
   role).
2. **Source-supplied ids.** Use an id the sources agree on. No source gives
   one: the ids are per source, and a company's Greenhouse id means nothing on
   an aggregator. Useful only for matching a posting to itself (already done by
   `(source, source_id)`).
3. **Fuzzy or embedding similarity.** Trigram similarity or nearest neighbours
   on embeddings, with a threshold. Finds near-duplicates, but needs a
   threshold that is tuned on labelled pairs (not available yet), is harder to
   explain, is not stable when the model or threshold changes, and cannot be
   a unique key on its own.
4. **LLM-assisted matching.** Ask a model whether two postings are the same
   job. Best judgement, but costly, slow, non-deterministic and subject to the
   free-tier quota that extraction already uses.

## Decision

Option 1 now, with room for options 3 and 4 later as a second pass.

**Fingerprint "fp1".** `"fp1:" + sha256(company, title, locations)`, each part
normalised as described in the docstring of `sanket/canonical/fingerprint.py`
(the source of truth for the exact algorithm). In short:

- Unicode NFKC and casefold; letters, digits and combining marks are kept and
  everything else collapses to a space. Accents are not folded, so Swedish and
  Bengali text is untouched and "malmö" is not "malmo".
- Company: legal-form words dropped from the end (inc, llc, ltd, gmbh, ab, ...),
  a leading "the" dropped, "&" read as "and", placeholders such as
  "confidential" treated as no company. Words such as "group" or "labs" are kept.
- Title: gender markers, bracketed work-mode decorations and trailing job or
  requisition ids removed; "sr" and "jr" expanded. Seniority and levels are
  never touched.
- Location: split on `; , / |`, remote and worldwide wording becomes one
  `remote` token, the parts are de-duplicated and sorted. Country codes are not
  guessed.
- A posting without a usable title or company has no fingerprint, stays
  ungrouped (`job_id` NULL) and is counted in the run summary.

The prefix is the algorithm version. Changing the algorithm means a new prefix
(`fp2:`), after which the next canonicalisation run recomputes every posting's
fingerprint, regroups it, and leaves the old jobs behind with a count of 0.

**Schema.** `job` (unique `fingerprint`, display `title`, `company`,
`location`, `representative_posting_id`, `posting_count`, `first_seen_at`,
`last_seen_at`, timestamps) and `posting.job_id`, nullable and indexed, with
`ON DELETE SET NULL` on both sides. The migration is expand-only, with no
backfill and no NOT NULL, so code that does not know about jobs keeps working.

**Aggregates.** `posting_count`, `first_seen_at` and `last_seen_at` come from
the member postings. The representative posting, which supplies the display
fields, is the member with a non-blank description, then the most recently
seen, then the lowest id. The canonicalisation run refreshes every job that
gained or lost a posting (the old job too) and re-syncs jobs whose count or
seen-times drifted after re-ingestion.

**Open or closed.** There is no `status` column. Whether a job is still open is
computed at query time from `last_seen_at` (for example "seen in the last 14
days"), because a stored flag would go stale as soon as time passes. The window
is a query-time choice and can differ by use. A job with `posting_count = 0` is
not open.

**Jobs are never deleted.** A job that loses its last posting keeps its row
with a count of 0, so ids held by future tables stay valid. Cleaning up empty
jobs, if ever needed, is a deliberate separate step after those tables exist.

**Race safety.** A job is created with `INSERT ... ON CONFLICT (fingerprint) DO
UPDATE`, so two runs that meet the same new fingerprint end up with one job.
Postings in a batch are locked (`FOR UPDATE`) so concurrent runs queue instead
of racing, and rows are written in a fixed order.

## Consequences

- **False splits.** Near-duplicates are not merged: "Sr. Engineer" and "Senior
  Software Engineer", the same role with a differently written city, a title
  with an extra word, a company written two ways. This shows as a duplicate in
  results and is the cheaper error.
- **Rare false merges.** Two different openings with the same normalised
  company, title and location become one job. Reposts of the same role with
  several requisitions are merged on purpose. On the local development data
  (about 6,400 postings) the run produced about 6,280 jobs, most merges being
  the same role listed by two aggregators or repeated per requisition.
- **Display flips.** The representative can change when postings are re-seen
  and a job is refreshed, so the display title may switch between sources.
- **Cost.** A full run reads every posting and recomputes fingerprints in
  Python. That is a few seconds at this size. Callers that know what they
  touched should use `canonicalise_postings(ids)`.
- **Evolving.** Planned, not built: a second pass that proposes merges between
  existing jobs with trigram similarity on the normalised fields or embedding
  nearest neighbours, accepts them above a confidence threshold tuned on
  labelled pairs, and records them in a merge table (loser, winner, score,
  method) instead of rewriting fingerprints. Postings then follow the winner,
  and an unmerge is a row deletion. The versioned prefix covers changes to the
  fingerprint itself. Option 4 is reserved for the uncertain middle band of that
  second pass.
