"""Decide, without touching the database, which job each posting belongs to."""

from collections.abc import Sequence
from dataclasses import dataclass

from sanket.canonical.fingerprint import fingerprint


@dataclass(frozen=True)
class PostingSnapshot:
    """A posting as read for canonicalisation, with the fingerprint of its current job."""

    id: int
    job_id: int | None
    title: str | None
    company: str | None
    location: str | None
    current_fingerprint: str | None


@dataclass(frozen=True)
class JobSeed:
    """Display fields for a job that does not exist yet, taken from its first posting."""

    fingerprint: str
    title: str
    company: str
    location: str | None


@dataclass(frozen=True)
class Plan:
    """What one batch of postings needs.

    `assignments` maps a posting id to the fingerprint of the job it must join, `detach`
    lists postings that must leave their job, and `old_job_ids` are the jobs that lose a
    posting and so need their aggregates refreshed.
    """

    assignments: dict[int, str]
    seeds: tuple[JobSeed, ...]
    detach: tuple[int, ...]
    old_job_ids: frozenset[int]
    linked: int = 0
    moved: int = 0
    unlinked: int = 0
    unchanged: int = 0
    no_fingerprint: int = 0


def _seed(fp: str, posting: PostingSnapshot) -> JobSeed:
    # A fingerprint exists only when the title and company have text, so they are not None.
    return JobSeed(fp, posting.title or "", posting.company or "", posting.location)


def plan_batch(postings: Sequence[PostingSnapshot]) -> Plan:
    assignments: dict[int, str] = {}
    seeds: dict[str, JobSeed] = {}
    detach: list[int] = []
    old_job_ids: set[int] = set()
    linked = moved = unlinked = unchanged = no_fingerprint = 0
    for posting in sorted(postings, key=lambda item: item.id):
        fp = fingerprint(title=posting.title, company=posting.company, location=posting.location)
        if fp is None:
            no_fingerprint += 1
            if posting.job_id is not None:
                detach.append(posting.id)
                old_job_ids.add(posting.job_id)
                unlinked += 1
            continue
        if posting.job_id is not None and posting.current_fingerprint == fp:
            unchanged += 1
            continue
        assignments[posting.id] = fp
        seeds.setdefault(fp, _seed(fp, posting))
        if posting.job_id is None:
            linked += 1
        else:
            old_job_ids.add(posting.job_id)
            moved += 1
    return Plan(
        assignments=assignments,
        seeds=tuple(sorted(seeds.values(), key=lambda seed: seed.fingerprint)),
        detach=tuple(detach),
        old_job_ids=frozenset(old_job_ids),
        linked=linked,
        moved=moved,
        unlinked=unlinked,
        unchanged=unchanged,
        no_fingerprint=no_fingerprint,
    )
