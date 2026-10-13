from sanket.hashing import content_hash, make_hash
from sanket.sources.base import NormalizedPosting


def test_make_hash_is_deterministic() -> None:
    job = {
        "company": "Acme",
        "position": "Backend Engineer",
        "description": "Build APIs",
        "location": "Remote",
    }
    assert make_hash(job) == make_hash(job)


def test_make_hash_differs_when_description_changes() -> None:
    job_a = {
        "company": "Acme",
        "position": "Backend Engineer",
        "description": "Build APIs",
        "location": "Remote",
    }
    job_b = {**job_a, "description": "Build APIs for workers"}
    assert make_hash(job_a) != make_hash(job_b)


def make_posting(**overrides) -> NormalizedPosting:
    data = {
        "source": "bdjobs",
        "source_id": "1",
        "url": "https://x.com",
        "title": "Dev",
        "raw": {},
    }
    data.update(overrides)
    return NormalizedPosting(**data)


def test_content_hash_has_version_prefix() -> None:
    assert content_hash(make_posting()).startswith("v1:")


def test_missing_and_none_company_hash_the_same() -> None:
    assert content_hash(make_posting()) == content_hash(make_posting(company=None))


def test_raw_changes_do_not_change_hash() -> None:
    a = make_posting(raw={})
    b = make_posting(raw={"standout": 1})
    assert content_hash(a) == content_hash(b)


def test_company_change_changes_hash() -> None:
    a = make_posting(company="Acme")
    b = make_posting(company="Globex")
    assert content_hash(a) != content_hash(b)
