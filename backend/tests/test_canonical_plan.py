from sanket.canonical.fingerprint import fingerprint
from sanket.canonical.plan import JobSeed, PostingSnapshot, plan_batch


def snapshot(
    posting_id: int,
    *,
    title: str | None = "Engineer",
    company: str | None = "Acme",
    location: str | None = "Berlin",
    job_id: int | None = None,
    current: str | None = None,
) -> PostingSnapshot:
    return PostingSnapshot(posting_id, job_id, title, company, location, current)


FP = fingerprint(title="Engineer", company="Acme", location="Berlin")


def test_unlinked_postings_are_linked_and_share_one_seed() -> None:
    plan = plan_batch([snapshot(2, title="Engineer (m/f/d)"), snapshot(1)])

    assert plan.assignments == {1: FP, 2: FP}
    assert plan.seeds == (JobSeed(FP or "", "Engineer", "Acme", "Berlin"),)
    assert (plan.linked, plan.moved, plan.unchanged) == (2, 0, 0)


def test_a_posting_already_on_the_right_job_is_unchanged() -> None:
    plan = plan_batch([snapshot(1, job_id=7, current=FP)])

    assert plan.assignments == {}
    assert plan.unchanged == 1
    assert plan.old_job_ids == frozenset()


def test_a_posting_whose_fingerprint_changed_is_moved_and_its_old_job_is_touched() -> None:
    plan = plan_batch([snapshot(1, title="Data Engineer", job_id=7, current=FP)])

    assert list(plan.assignments) == [1]
    assert plan.moved == 1
    assert plan.old_job_ids == frozenset({7})


def test_postings_without_a_usable_title_or_company_get_no_job() -> None:
    plan = plan_batch([snapshot(1, title=None), snapshot(2, company="  ")])

    assert plan.assignments == {}
    assert plan.seeds == ()
    assert plan.no_fingerprint == 2
    assert plan.detach == ()


def test_a_posting_that_lost_its_title_is_detached_from_its_job() -> None:
    plan = plan_batch([snapshot(1, title=None, job_id=7, current=FP)])

    assert plan.detach == (1,)
    assert plan.unlinked == 1
    assert plan.no_fingerprint == 1
    assert plan.old_job_ids == frozenset({7})


def test_the_seed_comes_from_the_lowest_posting_id() -> None:
    plan = plan_batch([snapshot(5, title="ENGINEER"), snapshot(3, title="Engineer")])

    assert plan.seeds[0].title == "Engineer"
