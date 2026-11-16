# Canonicalisation (operators)

Canonicalisation groups postings that describe the same real job into one row
of the `job` table and links each posting to it (`posting.job_id`). Why and how
the grouping works is in
[adr/0002-job-matching-strategy.md](adr/0002-job-matching-strategy.md); the
exact fingerprint algorithm is in the docstring of
`backend/src/sanket/canonical/fingerprint.py`.

## Before the first run

The `job` table and `posting.job_id` come from migration `e67e00d6f629`. As with
every migration, apply it to production with the **Migrate production database**
workflow from the feature branch **before** the code is merged and deployed.
The migration is additive and nullable, so the code on `main` keeps working
before and after it.

## Running it

From `backend/`:

```bash
python -m sanket.canonicalise            # dry run (default): reads only, writes nothing
python -m sanket.canonicalise --apply    # write the changes
python -m sanket.canonicalise --apply --batch-size 200
```

Always do the dry run first and check the numbers. `--apply` is safe to repeat
and to interrupt: each batch is its own transaction and a second run with no new
data changes nothing. Only `posting.job_id` and the `job` table are written;
`posting` content, `raw` and `updated_at` are never touched.

It also runs on its own at the end of every `python -m sanket.ingest`, after the
source summaries. A failure there is logged ("Canonicalisation failed") and never
fails the ingest. Set `CANONICALISE_AFTER_INGEST=false` to turn that step off,
for example while the migration has not been applied yet. The scheduled
workflow (`ingest.yml`) does not pass that variable, so on GitHub it is on by
default; the first run after the migration creates all jobs.

## Reading the summary line

```
canonicalise mode=apply scanned=6393 linked=6393 moved=0 unlinked=0 unchanged=0
  no_fingerprint=0 jobs_created=6276 jobs_refreshed=6276 jobs_resynced=0
```

| Field | Meaning |
|---|---|
| `mode` | `dry-run` counts only; `apply` wrote the changes. A dry run predicts the apply run. |
| `scanned` | Postings examined. |
| `linked` | Postings that had no job and now have one. |
| `moved` | Postings whose title, company or location changed and that now belong to a different job. |
| `unlinked` | Postings that lost their job because they no longer have a usable title or company. |
| `unchanged` | Postings already on the right job. |
| `no_fingerprint` | Postings with no usable title or company. They stay ungrouped (`job_id` NULL) and are never grouped on empty fields. |
| `jobs_created` | New `job` rows. |
| `jobs_refreshed` | Jobs whose count, seen-times, representative or display fields were recomputed because they gained or lost a posting (new jobs included). |
| `jobs_resynced` | Other jobs whose count or seen-times had drifted, for example after postings were seen again by ingestion or deleted. |

A second run straight after the first shows `linked`, `moved`, `unlinked`,
`jobs_created`, `jobs_refreshed` and `jobs_resynced` all at 0. After an ingest,
`jobs_resynced` is normally above 0: postings were seen again, so the jobs'
`last_seen_at` moves forward.

## Things to know

- A job whose last posting moved away keeps its row with `posting_count = 0`.
  Jobs are never deleted, so ids used by other tables stay valid.
- Whether a job is still open is not stored. Query it from `last_seen_at`, for
  example `last_seen_at > now() - interval '14 days' AND posting_count > 0`.
- Postings with `no_fingerprint` are expected for postings that have no title or
  a placeholder company ("Confidential"). A high count means a source is not
  filling those fields.
- To change the algorithm, add a new version prefix in `fingerprint.py`
  (`fp2`); the next run regroups every posting. Do not edit `fp1` in place:
  existing fingerprints would no longer match.
- Another process can call `canonicalise_postings(posting_ids)` from
  `sanket.canonical.service` right after it writes postings, to group just those
  and update their jobs without scanning the table.
