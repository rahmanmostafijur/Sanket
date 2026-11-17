# Profiles and matching (operators)

A profile says what someone is looking for. The matcher scores every job against
every profile it is close to and keeps the result in `job_match`. Why it is built
this way is in [adr/0006-profiles-and-matching.md](adr/0006-profiles-and-matching.md)
and the queue it runs on is in [adr/0005-task-queue.md](adr/0005-task-queue.md).

## Data flow

```
POST /profiles ──► profile (pending) ──► task embed_profile ──► profile_embedding, profile ready
                                                                  │
                                                                  └─► task match_profile ─┐
                                                                                          ▼
python -m sanket.indexing --apply ──► job_embedding written ──► task match_job ──► job_match
                          └─ job removed as dead ──► task match_job (withdraw) ──────────┘
                                                                                          │
                                                          MatchNotifier.notify (after commit)
```

- Saving a profile stores it and queues `embed_profile`. The embedding provider is
  never called in the request. Until the profile is `ready` it is not matched.
- `embed_profile` embeds the profile (only when its embedding hash changed) and queues
  `match_profile`, which matches the profile against jobs seen in the last
  `MATCH_RECENT_JOB_DAYS` days and scores its existing matches again.
- An applied indexing run queues `match_job` for every job whose embedding it wrote
  and a withdrawing `match_job` for every job it removed as dead. `match_job` matches
  the job against its nearest active, ready profiles.
- Tasks are idempotent and delivered at least once. A match keeps its id for life; a
  job that stops fitting is `withdrawn`, not deleted, and `active` again if it fits
  again.

Everything is derived from the database, so the queue can be lost without losing
anything: `embed-profiles` and `rematch` (below) queue or run the work again.

## What you need

| Piece | Needed for |
|---|---|
| Migration `c8199e1b7ec9` (tables `profile`, `profile_embedding`, `job_match`) | everything; apply it before the code is deployed |
| `REDIS_URL` and a worker | queued embedding and matching (`docker compose up -d redis`) |
| `GEMINI_API_KEY` | embedding profiles (the worker, or `embed-profiles --inline`) |
| An index (`python -m sanket.indexing --apply`) | jobs to match; see [indexing.md](indexing.md) |

## Running it

From `backend/`:

```bash
docker compose up -d redis              # once, from the repository root
python -m sanket.worker                 # works the queue until stopped
python -m sanket.worker --burst         # drains the queue and exits (tests, development)
```

The worker uses the forking `Worker` on Linux and `SimpleWorker` on Windows or with
`--simple`. A scheduler runs inside it: retries with backoff and delayed tasks only
elapse while a worker is running. Ctrl+C and SIGTERM are a warm shutdown (the task in
progress finishes). Without `REDIS_URL` it exits with a message; with an unreachable
Redis it says so without printing the URL. A task that fails is retried up to
`QUEUE_MAX_ATTEMPTS` times with backoff; one that cannot succeed (bad payload, input
the provider rejects, no `GEMINI_API_KEY`) goes to the dead-letter store at once.

```bash
python -m sanket.queue.dlq list                 # dead-lettered tasks, with the error
python -m sanket.queue.dlq requeue --all        # try them again with a full set of attempts
python -m sanket.queue.dlq purge <id>...        # or --all
```

### Embedding profiles

```bash
python -m sanket.matching embed-profiles                      # dry run: count and list
python -m sanket.matching embed-profiles --apply              # queue them for the worker
python -m sanket.matching embed-profiles --apply --inline     # embed and match now, here
```

Selects profiles that are `pending` or `failed`, or have no vector for the configured
model version (`--limit`, default 1000). Use it after Redis was down when profiles
were saved, after a quota failure, or after changing `EMBEDDING_MODEL_VERSION`.

### Matching again

```bash
python -m sanket.matching rematch --job 42                    # dry run for one job
python -m sanket.matching rematch --profile 7 --apply
python -m sanket.matching rematch --all-jobs --apply          # every live job with an embedding,
                                                              # plus dead jobs still holding matches
python -m sanket.matching rematch --all-profiles --since-days 2 --apply
python -m sanket.matching rematch --all-jobs --apply --inline # run now instead of queueing
```

`--since-days N` limits `--all-jobs` to jobs whose embedding changed in the last N days
and `--all-profiles` to profiles saved in the last N days. Both commands are dry runs
unless `--apply` is given and log their counts (`selected`, `queued`, `duplicate`,
`ran`, `failed`); the exit code is non-zero if anything failed or could not be queued.
`--inline` runs each task once here, so a provider failure marks a profile `failed`
immediately instead of being retried with backoff. Tasks already pending are counted as
`duplicate`, not queued twice.

## Without Redis

Nothing breaks. Profiles are saved and stay `pending`, indexing runs as before and
queues nothing (it logs that `REDIS_URL` is not set), and the API answers as usual.
Catch up with `--inline`:

```bash
python -m sanket.matching embed-profiles --apply --inline
python -m sanket.matching rematch --all-jobs --apply --inline
```

If Redis is configured but down during an indexing run, one error is logged and the
run's exit code and summary are unchanged; run `rematch --all-jobs --apply` afterwards.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `MATCH_ENQUEUE_AFTER_INDEXING` | `true` | Queue matching after an applied indexing run (needs `REDIS_URL`). |
| `MATCH_MIN_SCORE` | `0.55` | Blended score (0 to 1) a match needs; a profile can override it. |
| `MATCH_MIN_COSINE` | `0.5` | Embedding similarity floor; the cosine part is rescaled from here (0) to 1 (1). |
| `MATCH_WEIGHT_COSINE` / `_SKILLS` / `_TITLE` | `0.6` / `0.25` / `0.15` | Weights of the score parts; parts that do not apply are left out and the rest renormalised. |
| `MATCH_REQUIRED_SKILLS_MIN_FRACTION` | `1.0` | Share of a profile's required skills a job must list. |
| `MATCH_MAX_PROFILES_PER_JOB` | `200` | Nearest profiles examined for a changed job. |
| `MATCH_RECENT_JOB_DAYS` | `30` | Age limit of the jobs examined for a changed profile. |
| `MATCH_MAX_JOBS_PER_PROFILE` | `200` | Jobs examined for a changed profile. |
| `MAX_PROFILES_PER_OWNER` | `20` | Profiles an owner may have. |
| `DEFAULT_OWNER_ID` | `default` | Owner of requests without a credential, only with `AUTH_DEV_BYPASS=true` and `ENVIRONMENT=development` (ADR 0008). Otherwise the owner is the authenticated token subject. |
| `REDIS_URL`, `QUEUE_*`, `REDIS_TIMEOUT_SECONDS` | see `.env.example` | The queue (ADR 0005). |

Embedding settings are shared with indexing (`EMBEDDING_*`, `HNSW_EF_SEARCH`).

## Reading a match

`GET /profiles/{id}/matches` lists matches oldest first by match id; pass the last id
you saw as `after_id` for the next page (`include_withdrawn=true` adds withdrawn ones).
Each row of `job_match` stores `components`, the explanation of its score:

- `cosine`: the similarity, its rescaled part, weight, floor and whether it passed;
- `skills`: required hits and misses, preferred hits, whether the job lists skills;
- `title`: the best desired title and the share of its words found;
- `filters`: `pass`, `fail`, `unknown` or `na` for seniority, work mode, employment
  type, country and required skills; `unknown_fields` lists the filters passed only
  because the job's value is unknown;
- `location_match`, `threshold`.

## Tuning

The defaults are reasoned, not measured (ADR 0006). To tune from real data:

1. Look at what is stored: the score and its parts for active matches, and the near
   misses (withdrawn matches keep the score that failed):
   ```sql
   select status, round(score::numeric, 2) as score,
          components->'cosine'->>'value' as cosine, components->'filters' as filters
   from job_match order by updated_at desc limit 50;
   ```
2. Judge a sample by hand and move one setting at a time: `MATCH_MIN_COSINE` for
   irrelevant jobs that get through, `MATCH_MIN_SCORE` for the overall bar, the
   weights when skills or titles should matter more or less.
3. Apply it with `python -m sanket.matching rematch --all-jobs --apply` (queued).
   Matches whose score or components changed are updated in place; matches that
   no longer pass are withdrawn; **jobs that newly pass are new matches and are
   announced**, so loosening a threshold on a busy system notifies a lot at once.
4. If the algorithm itself changes, bump `SCORER_VERSION` in
   `sanket/matching/score.py`; stored matches with the old version count as changed.

## The notifier hook

`sanket.matching.notify.MatchNotifier` has one method, `notify(MatchRecord)`. It is
called once per new match (first match, or a withdrawn one that became active again,
with `reactivated=True`) after the transaction that wrote it has committed, so the row
is always readable. `notified_at` is set for the matches a hook call returned for. A
hook that raises is logged and does not fail or retry the task; that match stays with
`notified_at` NULL, which is also what a crash between commit and call leaves. The
next phase implements the hook (publishing to Redis for the live feed) and a sweep for
active matches whose `notified_at` is NULL. Hooks must be quick and must not assume
exactly-once delivery.

To wire one in, pass it as `notifier=` to `sanket.worker.run.run_worker` (from
`sanket/worker/__main__.py`) and to `CliContext` in the `sanket.matching` command; both
default to `NoopNotifier`, which accepts every match, so until a real hook exists
`notified_at` is set for matches without anything having been published.
