"""Match a changed job against the stored profiles, or a changed profile against recent jobs.

Job side (`match_job`): the job's embedding finds the nearest active, embedded profiles
(`MATCH_MAX_PROFILES_PER_JOB`, through the HNSW index); each is scored exactly. A job that has
died (no postings) or has no embedding withdraws all its matches. Active matches whose profile
is no longer among the candidates are withdrawn when the profile is switched off or was
examined and outranked; those of a profile that is waiting for its embedding are left alone.

Profile side (`match_profile`): the profile's embedding finds the nearest jobs seen within
`MATCH_RECENT_JOB_DAYS` (`MATCH_MAX_JOBS_PER_PROFILE`), and the profile's active matches are
scored again as well, so a changed profile also withdraws what it no longer wants. A profile
that is switched off withdraws everything; one that is not embedded yet is skipped.

Both are safe to repeat (see `sanket.matching.persist`). New matches are announced to the
notifier after the transaction has committed; a notifier failure is logged and changes nothing.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from sanket.db import engine
from sanket.indexing.filters import SearchFilters
from sanket.indexing.queries import vector_candidates
from sanket.matching.config import MatchConfig
from sanket.matching.loaders import (
    job_cosines,
    load_job_vector,
    load_job_views,
    load_profile_vector,
    load_profile_views,
    nearest_profiles,
)
from sanket.matching.notify import MatchNotifier, MatchRecord, NoopNotifier
from sanket.matching.persist import (
    Evaluation,
    StoredMatch,
    WriteKind,
    WritePlan,
    apply_plans,
    load_stored_for_job,
    load_stored_for_profile,
    mark_notified,
    plan_write,
    withdraw_job_matches,
    withdraw_matches,
    withdraw_profile_matches,
)
from sanket.matching.score import score_job_for_profile
from sanket.matching.types import JobView, ProfileView
from sanket.models import EmbeddingStatus, JobMatch, MatchStatus
from sanket.profiles.store import ProfileRow, load_profile

logger = logging.getLogger(__name__)

SKIP_NO_EMBEDDING = "no_embedding"
SKIP_MISSING = "missing"
SKIP_NOT_READY = "not_ready"


@dataclass(frozen=True)
class MatchSummary:
    evaluated: int = 0
    created: int = 0
    reactivated: int = 0
    updated: int = 0
    withdrawn: int = 0
    skipped: str | None = None


def _summary(evaluated: int, plans: Sequence[WritePlan], withdrawn: int) -> MatchSummary:
    kinds = [plan.kind for plan in plans]
    return MatchSummary(
        evaluated=evaluated,
        created=kinds.count(WriteKind.INSERT),
        reactivated=kinds.count(WriteKind.REACTIVATE),
        updated=kinds.count(WriteKind.UPDATE) + kinds.count(WriteKind.HASHES),
        withdrawn=withdrawn + kinds.count(WriteKind.WITHDRAW),
    )


def _plans(
    evaluations: Sequence[Evaluation], stored: dict[tuple[int, int], StoredMatch]
) -> list[WritePlan]:
    plans = (plan_write(stored.get((ev.profile_id, ev.job_id)), ev) for ev in evaluations)
    return [plan for plan in plans if plan is not None]


def _written(plans: Sequence[WritePlan], ids: dict[tuple[int, int], int]) -> list[WritePlan]:
    """The plans that took effect (a first match another worker inserted first did not)."""
    return [p for p in plans if (p.evaluation.profile_id, p.evaluation.job_id) in ids]


def _announce(
    plans: Sequence[WritePlan],
    ids: dict[tuple[int, int], int],
    owners: dict[int, str],
    notifier: MatchNotifier,
    db_engine: Engine,
) -> None:
    """Tell the notifier about the new matches, after the commit. Never raises."""
    delivered: list[int] = []
    for plan in plans:
        evaluation = plan.evaluation
        match_id = ids.get((evaluation.profile_id, evaluation.job_id))
        if not plan.is_new or match_id is None:
            continue
        record = MatchRecord(
            match_id=match_id,
            profile_id=evaluation.profile_id,
            owner_id=owners[evaluation.profile_id],
            job_id=evaluation.job_id,
            score=evaluation.score.score,
            components=evaluation.score.components,
            reactivated=plan.kind is WriteKind.REACTIVATE,
        )
        try:
            notifier.notify(record)
        except Exception:  # a subscriber must not be able to fail the matching
            logger.exception("Notifying match %d failed; the match is stored", match_id)
        else:
            delivered.append(match_id)
    try:
        with db_engine.begin() as conn:
            mark_notified(conn, delivered)
    except SQLAlchemyError:
        logger.exception("Recording %d notifications failed", len(delivered))


def _evaluate(job: JobView, view: ProfileView, cosine: float, cfg: MatchConfig) -> Evaluation:
    return Evaluation(
        profile_id=view.profile_id,
        job_id=job.job_id,
        score=score_job_for_profile(job, view, cosine, cfg),
        job_embedding_hash=job.embedding_hash,
        profile_hash=view.content_hash,
    )


# -- job side ---------------------------------------------------------------------------------


def withdraw_job(job_id: int, db_engine: Engine = engine) -> MatchSummary:
    """Withdraw every active match of a job that has died or lost its embedding."""
    with db_engine.begin() as conn:
        count = withdraw_job_matches(conn, [job_id])
    return MatchSummary(withdrawn=count, skipped=SKIP_NO_EMBEDDING)


def _outranked_ids(
    stored: dict[tuple[int, int], StoredMatch], examined: set[int], rows: dict[int, ProfileRow]
) -> list[int]:
    """Active matches whose profile was not examined and should no longer hold one."""
    ids = []
    for (profile_id, _), match in stored.items():
        if match.status != MatchStatus.ACTIVE or profile_id in examined:
            continue
        row = rows.get(profile_id)
        if row is None or not row.active or row.embedding_status == EmbeddingStatus.READY:
            ids.append(match.id)
    return ids


def match_job(
    job_id: int,
    cfg: MatchConfig,
    *,
    notifier: MatchNotifier | None = None,
    db_engine: Engine = engine,
) -> MatchSummary:
    notifier = notifier or NoopNotifier()
    with db_engine.connect() as conn:
        vector = load_job_vector(conn, job_id, cfg.spec)
    if vector is None:
        return withdraw_job(job_id, db_engine)
    cosines = dict(nearest_profiles(vector.embedding, cfg, db_engine))
    views = load_job_views([job_id], {job_id: vector.content_hash}, db_engine)
    if job_id not in views:
        return withdraw_job(job_id, db_engine)
    job = views[job_id]
    with db_engine.begin() as conn:
        profiles, _ = load_profile_views(conn, list(cosines))
        stored = load_stored_for_job(conn, job_id, list(cosines))
        evaluations = [_evaluate(job, view, cosines[pid], cfg) for pid, view in profiles.items()]
        plans = _plans(evaluations, stored)
        ids = apply_plans(conn, plans)
        plans = _written(plans, ids)
        others = {pid for pid, _ in stored if pid not in cosines}
        _, other_rows = load_profile_views(conn, sorted(others))
        withdrawn = withdraw_matches(conn, _outranked_ids(stored, set(cosines), other_rows))
    owners = {pid: view.owner_id for pid, view in profiles.items()}
    _announce(plans, ids, owners, notifier, db_engine)
    return _summary(len(evaluations), plans, withdrawn)


# -- profile side -------------------------------------------------------------------------------


def _active_match_job_ids(db_engine: Engine, profile_id: int) -> list[int]:
    stmt = select(JobMatch.job_id).where(
        JobMatch.profile_id == profile_id, JobMatch.status == MatchStatus.ACTIVE
    )
    with db_engine.connect() as conn:
        return list(conn.execute(stmt).scalars())


def match_profile(
    profile_id: int,
    cfg: MatchConfig,
    *,
    notifier: MatchNotifier | None = None,
    now: datetime | None = None,
    db_engine: Engine = engine,
) -> MatchSummary:
    notifier = notifier or NoopNotifier()
    with db_engine.connect() as conn:
        row = load_profile(conn, profile_id)
        vector = load_profile_vector(conn, profile_id, cfg.spec) if row else None
    if row is None:
        return MatchSummary(skipped=SKIP_MISSING)
    if not row.active:
        with db_engine.begin() as conn:
            return MatchSummary(withdrawn=withdraw_profile_matches(conn, profile_id))
    if row.embedding_status != EmbeddingStatus.READY or vector is None:
        return MatchSummary(skipped=SKIP_NOT_READY)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=cfg.recent_job_days)
    found = vector_candidates(
        vector.embedding,
        cfg.spec,
        cfg.max_jobs_per_profile,
        cfg.ef_search,
        db_engine,
        filters=SearchFilters(posted_after=cutoff),
    )
    held = _active_match_job_ids(db_engine, profile_id)
    job_ids = sorted({c.job_id for c in found} | set(held))
    with db_engine.connect() as conn:
        scored = job_cosines(conn, job_ids, vector.embedding, cfg.spec)
    views = load_job_views(job_ids, {j: h for j, (h, _) in scored.items()}, db_engine)
    view = ProfileView.from_row(row)
    with db_engine.begin() as conn:
        stored = load_stored_for_profile(conn, profile_id, job_ids)
        evaluations = [_evaluate(job, view, scored[jid][1], cfg) for jid, job in views.items()]
        plans = _plans(evaluations, stored)
        ids = apply_plans(conn, plans)
        plans = _written(plans, ids)
        gone = [m.id for (_, jid), m in stored.items() if jid not in views]
        withdrawn = withdraw_matches(conn, gone)
    _announce(plans, ids, {profile_id: view.owner_id}, notifier, db_engine)
    return _summary(len(evaluations), plans, withdrawn)
