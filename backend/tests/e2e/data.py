"""The recorded inputs of the end-to-end tests and what the pipeline is expected to make of them.

The payloads live in tests/fixtures/e2e (shaped like the real Greenhouse and Remotive
responses). The extraction answers are what a model would say about each posting: the
tests script them so that the expected matches and search results can be derived by hand.

The corpus (Acme's board lists the first three; Remotive lists the others, and repeats Acme's
senior backend job, so the two postings must become one job with two sources):

  Senior Backend Engineer   Acme Inc    remote  senior  Python, PostgreSQL, REST APIs  (2 postings)
  Data Scientist            Acme Inc    hybrid  mid     Python, pandas
  Frontend Developer        Acme Inc    remote  mid     React, TypeScript
  Python DevOps Engineer    Beta Corp   remote  mid     Python, Kubernetes
  Office Manager            Gamma Ltd   onsite  mid     none
  Staff Python Engineer     Delta Labs  remote  lead    Python, REST APIs   (appears in a later run)
"""

from typing import Any

from sanket.sources.greenhouse import GreenhouseSource
from sanket.sources.remotive import RemotiveSource
from tests.search_helpers import extraction_data
from tests.source_helpers import load_json

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"

BACKEND = "Senior Backend Engineer"
DATA_SCIENTIST = "Data Scientist"
FRONTEND = "Frontend Developer"
DEVOPS = "Python DevOps Engineer"
OFFICE = "Office Manager"
STAFF = "Staff Python Engineer"

# Postings of the first run: 3 from Greenhouse and 3 from Remotive.
FIRST_RUN_POSTINGS = 6
# Jobs after canonicalisation: the backend job is listed by both sources.
FIRST_RUN_JOBS = 5

EXTRACTIONS: dict[str, dict[str, Any]] = {
    BACKEND: extraction_data(
        title=BACKEND, company="Acme Inc", skills=["Python", "PostgreSQL", "REST APIs"]
    ),
    DATA_SCIENTIST: extraction_data(
        title=DATA_SCIENTIST,
        company="Acme Inc",
        seniority="mid",
        work_mode="hybrid",
        skills=["Python", "pandas"],
    ),
    FRONTEND: extraction_data(
        title=FRONTEND,
        company="Acme Inc",
        seniority="mid",
        skills=["React", "TypeScript"],
    ),
    DEVOPS: extraction_data(
        title=DEVOPS,
        company="Beta Corp",
        seniority="mid",
        country=None,
        city=None,
        skills=["Python", "Kubernetes"],
    ),
    OFFICE: extraction_data(
        title=OFFICE,
        company="Gamma Ltd",
        seniority="mid",
        work_mode="onsite",
        country="BD",
        city="Dhaka",
        skills=[],
    ),
    STAFF: extraction_data(
        title=STAFF,
        company="Delta Labs",
        seniority="lead",
        country=None,
        city=None,
        skills=["Python", "REST APIs"],
    ),
}

# Remote Python work at any seniority: of the corpus only the backend and the DevOps job fit
# (the data scientist job is hybrid, the frontend job lists no Python, the office job is onsite).
PROFILE_BODY: dict[str, Any] = {
    "name": "Remote Python",
    "summary": "backend engineer python postgresql apis",
    "desired_titles": ["Backend Engineer"],
    "required_skills": ["Python"],
    "work_modes": ["remote"],
}
EXPECTED_FIRST_MATCHES = sorted([BACKEND, DEVOPS])


def greenhouse_feed() -> tuple[GreenhouseSource, dict[str, object]]:
    return GreenhouseSource(["acme"]), {GREENHOUSE_URL: load_json("e2e/greenhouse_acme.json")}


def remotive_feed(
    fixture: str = "e2e/remotive_jobs.json",
) -> tuple[RemotiveSource, dict[str, object]]:
    return RemotiveSource(), {REMOTIVE_URL: load_json(fixture)}


def first_run_feeds() -> list[tuple[Any, dict[str, object]]]:
    return [greenhouse_feed(), remotive_feed()]


def second_run_feeds() -> list[tuple[Any, dict[str, object]]]:
    """The same boards, with one new Remotive listing."""
    return [greenhouse_feed(), remotive_feed("e2e/remotive_new_job.json")]
