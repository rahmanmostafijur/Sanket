"""A small synthetic corpus for the evaluation tests and backend/eval/queries.example.jsonl.

Every job is invented (made-up companies, no real people or postings). The fingerprints are
computed with the real `fingerprint()`, so the labelled example file refers to the same
references a real canonicalisation of these postings would produce.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from sanket.canonical.fingerprint import fingerprint
from tests.search_helpers import add_search_job, extraction_data


@dataclass(frozen=True)
class EvalJob:
    key: str
    title: str
    company: str
    location: str
    description: str
    skills: tuple[str, ...]
    work_mode: str = "remote"

    @property
    def fingerprint(self) -> str:
        value = fingerprint(title=self.title, company=self.company, location=self.location)
        assert value is not None
        return value

    def extraction(self) -> dict[str, Any]:
        return extraction_data(
            title=self.title,
            company=self.company,
            skills=list(self.skills),
            work_mode=self.work_mode,
        )


EVAL_JOBS: tuple[EvalJob, ...] = (
    EvalJob(
        "python_backend",
        "Senior Python Backend Engineer",
        "Northwind Labs",
        "Berlin, Germany",
        "<p>Build and scale REST APIs in Python with PostgreSQL and Django.</p>",
        ("Python", "PostgreSQL", "Django"),
    ),
    EvalJob(
        "django_dev",
        "Python Developer",
        "Fjord Systems",
        "Oslo, Norway",
        "<p>Backend services in Django, mostly Python, with some frontend templates.</p>",
        ("Python", "Django"),
        work_mode="hybrid",
    ),
    EvalJob(
        "frontend",
        "Frontend Engineer",
        "Pixel Garden",
        "Remote",
        "<p>Build React and TypeScript interfaces for a design tool.</p>",
        ("React", "TypeScript", "CSS"),
    ),
    EvalJob(
        "data_scientist",
        "Data Scientist",
        "Quantum Bakery",
        "London, United Kingdom",
        "<p>Statistics and machine learning in Python to forecast demand.</p>",
        ("Python", "Machine learning", "Statistics"),
        work_mode="onsite",
    ),
    EvalJob(
        "ml_engineer",
        "Machine Learning Engineer",
        "Neural Nest",
        "Remote",
        "<p>Train and deploy machine learning models with PyTorch and Python.</p>",
        ("PyTorch", "Python", "MLOps"),
    ),
    EvalJob(
        "devops",
        "DevOps Engineer",
        "Cloudy Co",
        "Stockholm, Sweden",
        "<p>Run Kubernetes clusters and manage infrastructure with Terraform on AWS.</p>",
        ("Kubernetes", "Terraform", "AWS"),
        work_mode="hybrid",
    ),
    EvalJob(
        "swedish_java",
        "Systemutvecklare Java",
        "Nordisk Data AB",
        "Malmö, Sverige",
        "<p>Vi söker en systemutvecklare med erfarenhet av Java och Spring.</p>",
        ("Java", "Spring"),
        work_mode="onsite",
    ),
    EvalJob(
        "bengali_engineer",
        "সফটওয়্যার ইঞ্জিনিয়ার",
        "Dhaka Tech",
        "ঢাকা, বাংলাদেশ",
        "<p>আমরা একজন সফটওয়্যার ইঞ্জিনিয়ার খুঁজছি যিনি পাইথন জানেন।</p>",
        ("Python",),
        work_mode="onsite",
    ),
    EvalJob(
        "support",
        "Customer Support Specialist",
        "Helpful Inc",
        "Remote",
        "<p>Answer customer tickets and keep our support queue healthy.</p>",
        ("Customer support", "Zendesk"),
    ),
    EvalJob(
        "designer",
        "Product Designer",
        "Pixel Garden",
        "Remote",
        "<p>Design interfaces in Figma and run user research.</p>",
        ("Figma", "UX"),
    ),
    EvalJob(
        "go_backend",
        "Backend Engineer",
        "Gopher Works",
        "Remote",
        "<p>Go microservices, gRPC and Kubernetes in production.</p>",
        ("Go", "gRPC", "Kubernetes"),
    ),
    EvalJob(
        "qa",
        "Junior QA Engineer",
        "Testwell",
        "Manila, Philippines",
        "<p>Write automated tests with Selenium and report defects.</p>",
        ("Selenium", "Test automation"),
        work_mode="onsite",
    ),
    EvalJob(
        "nurse",
        "Registered Nurse",
        "City Clinic",
        "Toronto, Canada",
        "<p>Patient care on a surgical ward.</p>",
        ("Patient care",),
        work_mode="onsite",
    ),
)

FINGERPRINTS = {job.key: job.fingerprint for job in EVAL_JOBS}


def seed_eval_corpus(engine: Engine) -> dict[str, int]:
    """Insert the corpus as canonical jobs; returns job ids by key."""
    return {
        job.key: add_search_job(
            engine,
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            extraction=job.extraction(),
            fingerprint=job.fingerprint,
        )
        for job in EVAL_JOBS
    }
