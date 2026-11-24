# Handoff (2026-11-25)

Where Phase 1 (LLM extraction and sources) stands, and exactly what is left. Phase 2 does
not start until the owner says so.

## Current state

- `main` holds all work so far; CI (`check` and `image`) passes locally: migrate, `alembic
  check`, ruff lint and format, mypy, 1724 tests with 0 skipped.
- Extraction results live in `posting_extraction`. The scheduled Ingest workflow extracts up
  to `EXTRACTION_BATCH_LIMIT` (50) postings per run, then (only when the `GEMINI_API_KEY`
  secret is set) indexes up to 500 changed jobs and matches the jobs embedded in the last day
  inline. Those two steps never fail the run.
- The backlog command is `python -m sanket.extract_backfill`. It stops cleanly at the cost cap
  (`EXTRACT_BACKFILL_MAX_COST_USD`, default 5 USD; do not raise it), at the daily cap
  (`EXTRACT_BACKFILL_DAILY_CAP`, 500; counted in Redis when `REDIS_URL` is set, otherwise per
  run), or when the Gemini daily quota runs out, and logs one summary line with tokens,
  estimated cost and `remaining_pending`.
- The backfill has run on the **local** database only (`.env` points at
  `127.0.0.1:5433/sanket`, not Neon).

## Done

- CI Format step fixed (ruff format on `extraction/facts.py` and `extraction/reindex.py`).
- Why no matches appeared after 23 Nov 20:03 UTC: postings do arrive (about 1,700 new per
  Ingest run; the hash gate works), but nothing indexed or matched them. The matcher only sees
  jobs with an embedding, and Ingest never ran indexing; the local app also reads the local
  database, which the workflow does not write. Ingest now indexes and matches.
- Local backfill: 315 postings extracted (49 + 266), 675,252 input and 50,515 output tokens,
  about 0.33 USD estimated (about 0.00104 USD per posting at 0.30 / 2.50 USD per million
  input / output tokens). Stopped on the Gemini daily quota; 8,772 postings left pending.
- Filters now have data: on 9,102 live jobs, remote 19 -> 167, hybrid 5 -> 110, on-site
  0 -> 18, senior 16 -> 104, lead 14 -> 112, full-time 36 -> 303, contract 0 -> 10.
- `plain_text` no longer leaves a lone "-"; the frontend skips the stream token without a
  credential, remembers the "tokens disabled" 404, and honours `Retry-After` on a 429.
- Sources: none added. Arbeitnow and Adzuna stay skipped (docs/sources.md). No Bangladeshi
  site has an official API or RSS whose terms allow reuse (Bdjobs robots.txt blocks all
  other bots; Skill.jobs terms ban aggregation; Chakri, BDjobsToday, NextJobz, Shomvob,
  Prothom Alo Jobs and the government portals publish no feed).

## Remaining (in order)

Run from `backend/` with the venv active. Never write the Neon URL into `.env` or the repo;
set it for the shell only and unset it afterwards. Stop and ask the owner if a secret (the
Neon URL) or a paid plan is needed.

### 1. Backfill on Neon (about 8,772 postings, in daily batches)

Needs the Neon `DATABASE_URL` from the owner.

```bash
export DATABASE_URL='<Neon URL from the owner>'   # shell only
alembic current                                   # must equal: alembic heads
alembic heads
```

If `alembic current` is behind `alembic heads` (for example `bc1e664ce683`, saved jobs, is
missing), do not run alembic against Neon by hand: run the "Migrate production database"
workflow and wait for it to finish, then check again.

```bash
gh workflow run migrate.yml -f confirm=migrate
gh run watch "$(gh run list --workflow=migrate.yml -L 1 --json databaseId -q '.[0].databaseId')"
```

Then one batch per day (the daily cap is per run without Redis, so run once a day):

```bash
python -m sanket.extract_backfill --limit 500 --no-reindex
```

Read the summary line (`ok=`, `input_tokens=`, `output_tokens=`, `estimated_cost_usd=`,
`remaining_pending=`, `stop=`). `stop=the provider's daily quota is used up` or `stop=daily
cap ...` is a clean stop; run again the next day. The scheduled Ingest runs use the same
Gemini key, so a day's batch may stop earlier. `unset DATABASE_URL` afterwards.

### 2. Re-embed the jobs left without a fresh embedding

9 jobs failed embedding (429) after the first local batch, and the 266-posting run used
`--no-reindex`; a local dry run shows at least 500 jobs waiting. Embedding has its own free
quota, so go in batches and stop when it returns 429:

```bash
python -m sanket.indexing --dry-run
python -m sanket.indexing --apply --limit 100
python -m sanket.matching rematch --all-jobs --since-days 1 --apply --inline
```

Do the same against Neon after step 1 (the Ingest workflow also does up to 500 per run).

### 3. Measure what each Ingest run sends to extraction, and its cost

```bash
for id in $(gh run list --workflow=ingest.yml -L 4 --json databaseId -q '.[].databaseId'); do
  gh run view "$id" --log | grep -E "summary source=|extraction summary"
done
```

Per run: new + updated postings (sources not in `EXTRACTION_EXCLUDED_SOURCES`, so not
`remoteok`) versus the `ok=` / `failed=` count of the extraction summary (capped at 50).
Estimate: postings extracted per day x 0.00104 USD, and x 30 for a month; also the cost if
every new posting were extracted (new per run x 4 runs a day). Report both; change nothing.

### 4. Careerjet terms (Bangladesh, locale `en_BD`)

Read https://www.careerjet.com/partners/api and the publisher terms. Questions: may results
be stored and shown later (the API requires the end user's `user_ip` and `user_agent` on
every call, which suits live searches, not scheduled ingestion), is attribution required,
and are there rate limits. If the terms are only visible after creating a publisher account,
stop and tell the owner. Record the outcome in docs/sources.md; add no source.

### 5. Stop

Report the results of 1 to 4 and wait for the owner's go-ahead before Phase 2.
