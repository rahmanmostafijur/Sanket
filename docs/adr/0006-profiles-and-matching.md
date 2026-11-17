# 0006: Profiles and matching

Status: accepted

## Context

Search (ADR 0004) answers a question asked now. Matching answers a standing one: a
user saves a profile, describing what they look for, and gets told when a job
that fits appears (and when one stops fitting). Phase 6 builds the part that
decides: store profiles, embed them, score jobs against them in both directions,
keep the results, and say when a match is new. Delivering the notification (a
live feed) is the next phase and plugs in through a hook.

Constraints that shaped the design:

- Jobs change all day (ingest, extraction, canonicalisation, indexing), profiles
  change when a user edits them, and both must lead to the same stored result
  whichever side moves first.
- Work runs on a queue with at-least-once delivery (ADR 0005), so repeating a
  task must be harmless and must not notify twice.
- There are no labelled matches yet. The score has to be explainable and its
  knobs honest about being untuned, as with search.
- Extractions are partial: a job often has no seniority, work mode or country.
- The provider free tier is small, and embeddings are the expensive step.

## Decisions

**1. A profile is criteria plus a name and an `active` flag.** Criteria: desired
titles, required and preferred skills, seniorities, work modes, employment types,
countries (ISO 3166-1 alpha-2), free-text locations, a summary, and an optional
per-profile minimum score. Everything is bounded and validated on the way in
(`sanket/profiles/criteria.py`: length limits, NUL refused, lists de-duplicated
ignoring case, `unknown` refused as a wish, unknown fields refused, at least a
title, a skill or a summary). A profile always belongs to one owner; until
authentication exists every request acts as `DEFAULT_OWNER_ID` and a profile of
another owner is a 404.

**2. Profiles are embedded behind a hash gate, as queries.** Saving a profile
stores it and queues `embed_profile`; the provider is never called in the
request. The embedding text is a fixed, ordered rendering of the criteria
(`sanket/profiles/text.py`), embedded with `embed_query`: a profile states a need
that is compared with job documents (`RETRIEVAL_DOCUMENT`), the asymmetric
pairing the model is trained for. Two hashes decide what runs again. The
**content hash** covers the canonicalised criteria and `active` (not the name, so
renaming does nothing); the **embedding hash** covers the text, model, version
and dimension. The provider is called only when no stored embedding has the
current embedding hash, and the vector is stored only if the profile still has
the content that was embedded (a save that landed meanwhile keeps it `pending`).
Status moves `pending` to `ready`, or to `failed` on the last attempt or on input
the provider rejects. Only `ready` and `active` profiles are matched.

**3. Scoring: hard filters, then a blend of the parts that apply.** The scorer
(`sanket/matching/score.py`) is a pure function.

- *Hard filters.* Seniority, work mode, employment type and country apply when the
  profile lists values for them; a known job value must be one of them. Required
  skills: the job must list at least `MATCH_REQUIRED_SKILLS_MIN_FRACTION` of them
  (all, by default), compared ignoring case and spacing.
- *Parts*, each in [0, 1]. `cosine`: the embedding similarity rescaled from
  `MATCH_MIN_COSINE` to 1. `skills`: (2 x required hits + preferred hits) over
  (2 x required + preferred) listed, so a must-have counts double. `title`: for the
  best desired title, the share of its words found in the job title.
- *Blend.* The weighted mean of the parts that apply
  (`MATCH_WEIGHT_COSINE/SKILLS/TITLE`, 0.6 / 0.25 / 0.15), so a profile without
  skills or titles is not dragged down for something it never asked for.
- *Match* when the filters hold, the cosine is at least `MATCH_MIN_COSINE` and the
  score reaches the profile's override or `MATCH_MIN_SCORE`.

Why these defaults: the embedding is the only part that sees meaning ("backend
developer" for "server-side engineer"), so it carries most of the weight; skills
are explicit evidence the user cared about; title words are cheap and noisy, so
they weigh least. `MATCH_MIN_COSINE = 0.5` is a floor below which two texts are
treated as unrelated whatever the other parts say, and `MATCH_MIN_SCORE = 0.55`
means that with the cosine alone a pair needs a similarity of about 0.78 (after
rescaling), with the other parts pulling it either way. Required skills default
to "all" because a user who marks a skill required means it. **These are
reasoned starting points, not tuned values**: there is no labelled data, so every
number is a setting and the components of every score are stored with the match
to make tuning possible (docs/matching.md). `SCORER_VERSION` is stored with each
match; changing the algorithm bumps it and a stored match with another version
counts as changed.

**4. Unknown fields pass the filter and are said so.** When the job's value for a
filtered field is unknown (the extraction could not tell, or there is none), the
job passes that filter and the field is listed in `components.unknown_fields`.
The alternative, rejecting such jobs, would hide most of the corpus from a
profile that sets a seniority, and the embedding and the other filters still
apply. A job with no extracted skills at all passes the required-skills filter the
same way. A known value that is not wanted fails the filter.

**5. Matching works from both sides.** A changed job (`match_job`) finds its
nearest active, embedded profiles through the HNSW index
(`MATCH_MAX_PROFILES_PER_JOB`) and scores each exactly. A changed profile
(`match_profile`) finds the nearest jobs seen in the last `MATCH_RECENT_JOB_DAYS`
(`MATCH_MAX_JOBS_PER_PROFILE`) and also scores again the matches it already holds,
so an edited profile withdraws what it no longer wants even when the job is no
longer among the nearest. A job that has died or lost its embedding withdraws all
its matches; a switched-off profile withdraws all of its. A profile that is
waiting for its embedding is left alone, not treated as outranked. Only vectors of
the configured model name and version are compared.

**6. Persistence is idempotent.** A pure function (`plan_write`) turns the stored
row and the new evaluation into the one write that is needed, or none: no row and
a match inserts; active and unchanged writes nothing (a change of hashes only is
written without touching `updated_at`); active and changed updates in place;
active and no longer a match withdraws; withdrawn and a match again reactivates;
withdrawn and still not a match writes nothing. Rows to decide on are read
`FOR UPDATE` in the transaction that writes, so two workers on the same job or
profile queue up. A pair that has no row yet cannot be locked, so a first match is
written with `INSERT ... ON CONFLICT DO NOTHING` and only the worker whose insert
took effect announces it (found by a concurrency test: both used to announce).
Running a task twice therefore changes nothing: same ids, no sequence value used,
`updated_at` unchanged.

**7. Notification happens after the commit, and `notified_at` is the marker.** A
match is new when first inserted and when a withdrawn one becomes active again.
The matcher calls `MatchNotifier.notify` once the transaction has committed, so a
subscriber that reads the database finds the row. `notified_at` is set for the
matches the hook accepted. A hook that raises is logged and neither fails nor
retries the task; the match stays stored with `notified_at` NULL, as does one whose
announcement was lost to a crash between commit and call, so a later sweep (an
active match with no `notified_at`) finds what was missed. Reactivation resets
`notified_at`. Hooks must be quick and tolerate duplicates.

**8. Indexing triggers matching, and nothing breaks indexing.** An applied
indexing run reports the jobs whose embedding it wrote and the jobs it removed as
dead to an optional observer. The observer queues `match_job` keyed by job and
embedding hash (so one embedding is matched once while pending), and a withdrawing
`match_job` (embedding hash `none`) for removed jobs. It is off without
`REDIS_URL` or with `MATCH_ENQUEUE_AFTER_INDEXING=false`, queues nothing for a
dry run, and a queue failure is logged once (it stops at the first failure
instead of waiting on a timeout per job), changing neither the exit code nor the
summary line. `sanket.indexing` itself imports neither RQ nor Redis. The queue is a
latency device: `python -m sanket.matching rematch` re-derives all of it from the
database.

**9. Matches are never deleted, they are withdrawn.** A match keeps its id for
life; the id only grows (identity column) and is what the live feed and the REST
page use as event id and resume point (`after_id`). Deleting and re-inserting
would change ids under a client that is paging, and lose the history of why a job
stopped fitting (the new score and components are stored with the withdrawal). A
withdrawn match that fits again is reactivated, with the same id, and announced as
reactivated. Clients list active matches by default and withdrawn ones on request.
Matches are deleted only with their profile or job (cascade).

## Consequences

- Without Redis everything but the asynchronous parts works: profiles are saved
  and stay `pending`, indexing runs unchanged, and
  `python -m sanket.matching embed-profiles|rematch --apply --inline` does the work
  in a process.
- The scorer is deterministic and the explanation is stored, so a match can be
  audited and thresholds tuned from real data; all numbers are untuned until there
  is labelled feedback. A tuning change is a settings change plus
  `rematch --all-jobs`; an algorithm change bumps `SCORER_VERSION`.
- A profile that is only ever compared with recent jobs will not see an older job
  until that job changes (the job side has no recency limit, so any change to the
  job matches it against everyone). `rematch --all-profiles` with a wider
  `MATCH_RECENT_JOB_DAYS` covers a backfill.
- A profile that passes the nearest-neighbour cut for a job but is crowded out when
  more profiles exist is withdrawn on the next match of that job; raising
  `MATCH_MAX_PROFILES_PER_JOB` costs a longer vector query.
- A lost notification is detectable but not retried automatically in this phase;
  the feed phase owns the sweep.
- Changing the profile text format or the model re-embeds every profile once
  (the hash gate); changing the model version needs `embed-profiles` to give every
  profile a vector for it.
