from sanket.hashing import make_hash


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
