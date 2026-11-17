"""The scoring function: how well one job fits one profile. Pure: no database, no clock.

The exact algorithm and the reasoning behind the defaults are in
docs/adr/0006-profiles-and-matching.md. In short:

1. Hard filters. Seniority, work mode, employment type and country apply when the profile
   lists values for them. A job whose value is unknown (the extraction could not tell, or
   there is none) passes the filter and is annotated in `components["unknown_fields"]`;
   a known value must be one of those listed. Required skills: the job must list at least
   `required_skills_min_fraction` of them (all by default), compared ignoring case and extra
   spaces; a job with no extracted skills at all passes, annotated.
2. Parts of the score, each in [0, 1]. `cosine`: the embedding cosine similarity rescaled from
   `min_cosine` (0) to 1 (1). `skills`: (2 * required hits + preferred hits) divided by
   (2 * required + preferred) listed by the profile; not applicable without skills on either
   side. `title`: for the best desired title, the share of its words found in the job
   title; not applicable without desired titles.
3. The score is the weighted mean of the parts that apply, so a part that cannot be judged
   does not drag the score down or up.
4. A job is a match when the filters hold, the cosine similarity is at least `min_cosine`
   and the score reaches the profile's `min_score_override` or the configured `min_score`.

Bump SCORER_VERSION whenever any of this changes in a way that can change a score: stored
matches carry the version, and a different version makes a stored match count as changed.
"""

import math
import re
from typing import Any

from sanket.matching.config import MatchConfig
from sanket.matching.types import JobView, MatchScore, ProfileView

SCORER_VERSION = 1

ROUND_DIGITS = 6
# Skills in the cosine-to-score blend count this many times more than preferred ones.
REQUIRED_SKILL_WEIGHT = 2
WORD = re.compile(r"\w+")

FILTER_NOT_APPLIED = "na"
FILTER_PASS = "pass"
FILTER_UNKNOWN = "unknown"
FILTER_FAIL = "fail"


def _round(value: float) -> float:
    return round(value, ROUND_DIGITS)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _skill_key(skill: str) -> str:
    return " ".join(skill.split()).casefold()


def _words(text: str) -> set[str]:
    return set(WORD.findall(text.casefold()))


def _value_filter(wanted: frozenset[str], actual: str | None) -> str:
    if not wanted:
        return FILTER_NOT_APPLIED
    if actual is None:
        return FILTER_UNKNOWN
    return FILTER_PASS if actual in wanted else FILTER_FAIL


def _skill_hits(profile_skills: tuple[str, ...], job_keys: set[str]) -> tuple[list[str], list[str]]:
    hits = [skill for skill in profile_skills if _skill_key(skill) in job_keys]
    missing = [skill for skill in profile_skills if _skill_key(skill) not in job_keys]
    return hits, missing


def _required_filter(profile: ProfileView, hits: int, job_known: bool, fraction: float) -> str:
    if not profile.required_skills:
        return FILTER_NOT_APPLIED
    if not job_known:
        return FILTER_UNKNOWN
    needed = math.ceil(fraction * len(profile.required_skills) - 1e-9)
    return FILTER_PASS if hits >= needed else FILTER_FAIL


def _cosine_part(cosine: float, cfg: MatchConfig) -> float:
    return _clamp((cosine - cfg.min_cosine) / (1.0 - cfg.min_cosine))


def _skills_part(
    profile: ProfileView, req_hits: list[str], pref_hits: list[str], job_known: bool
) -> float | None:
    total = REQUIRED_SKILL_WEIGHT * len(profile.required_skills) + len(profile.preferred_skills)
    if total == 0 or not job_known:
        return None
    return (REQUIRED_SKILL_WEIGHT * len(req_hits) + len(pref_hits)) / total


def _title_part(profile: ProfileView, job: JobView) -> tuple[float | None, str | None]:
    job_words = _words(job.title)
    best: tuple[float, str | None] = (0.0, None)
    scored = False
    for title in profile.desired_titles:
        wanted = _words(title)
        if not wanted:
            continue
        scored = True
        share = len(wanted & job_words) / len(wanted)
        if share > best[0]:
            best = (share, title)
    return (best[0], best[1]) if scored else (None, None)


def _blend(parts: list[tuple[float | None, float]]) -> float:
    """Weighted mean of the parts that apply; with all weights zero, the first part."""
    applicable = [(value, weight) for value, weight in parts if value is not None]
    total = sum(weight for _, weight in applicable)
    if not applicable:
        return 0.0
    if total == 0:
        return applicable[0][0]
    return sum(value * weight for value, weight in applicable) / total


def _location_match(profile: ProfileView, job: JobView) -> bool | None:
    if not profile.locations or job.location is None:
        return None
    where = job.location.casefold()
    return any(place.casefold() in where for place in profile.locations)


def score_job_for_profile(
    job: JobView, profile: ProfileView, cosine: float, cfg: MatchConfig
) -> MatchScore:
    """Score `job` for `profile`; `cosine` is the similarity of their embeddings."""
    job_keys = {_skill_key(skill) for skill in job.skills}
    skills_known = bool(job_keys)
    req_hits, req_missing = _skill_hits(profile.required_skills, job_keys)
    pref_hits, _ = _skill_hits(profile.preferred_skills, job_keys)
    filters = {
        "seniority": _value_filter(profile.seniorities, job.seniority),
        "work_mode": _value_filter(profile.work_modes, job.work_mode),
        "employment_type": _value_filter(profile.employment_types, job.employment_type),
        "country": _value_filter(profile.countries, job.country),
        "required_skills": _required_filter(
            profile, len(req_hits), skills_known, cfg.required_skills_min_fraction
        ),
    }
    passed_filters = FILTER_FAIL not in filters.values()

    cosine_part = _cosine_part(cosine, cfg)
    skills_part = _skills_part(profile, req_hits, pref_hits, skills_known)
    title_part, best_title = _title_part(profile, job)
    score = _clamp(
        _blend(
            [
                (cosine_part, cfg.weight_cosine),
                (skills_part, cfg.weight_skills),
                (title_part, cfg.weight_title),
            ]
        )
    )
    score = _round(score)
    threshold = (
        profile.min_score_override if profile.min_score_override is not None else cfg.min_score
    )
    cosine_ok = cosine >= cfg.min_cosine
    components: dict[str, Any] = {
        "cosine": {
            "value": _round(cosine),
            "part": _round(cosine_part),
            "weight": cfg.weight_cosine,
            "min": cfg.min_cosine,
            "ok": cosine_ok,
        },
        "skills": {
            "part": None if skills_part is None else _round(skills_part),
            "weight": cfg.weight_skills,
            "required_hits": req_hits,
            "required_missing": req_missing,
            "preferred_hits": pref_hits,
            "job_skills_known": skills_known,
        },
        "title": {
            "part": None if title_part is None else _round(title_part),
            "weight": cfg.weight_title,
            "best": best_title,
        },
        "filters": filters,
        "unknown_fields": sorted(
            name for name, state in filters.items() if state == FILTER_UNKNOWN
        ),
        "location_match": _location_match(profile, job),
        "threshold": threshold,
    }
    return MatchScore(
        score=score,
        components=components,
        passed_filters=passed_filters,
        is_match=passed_filters and cosine_ok and score >= threshold,
    )
