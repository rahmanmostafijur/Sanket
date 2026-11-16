import pytest

from sanket.extraction.schema import JobExtraction
from sanket.indexing import document
from sanket.indexing.document import (
    DOCUMENT_FORMAT_VERSION,
    JobFields,
    PostingFields,
    build_embedding_text,
    build_search_document,
    build_weighted_text,
    embedding_hash,
    search_hash,
)
from tests.test_extraction_schema import valid_data

JOB = JobFields(title="Backend Engineer", company="Acme", location="Berlin")
LIMIT = 3000


def extraction(**changes: object) -> JobExtraction:
    return JobExtraction.model_validate({**valid_data(), **changes})


def test_full_document_text_has_the_documented_format() -> None:
    doc = build_search_document(
        JOB, extraction(), PostingFields("<p>Build APIs.</p><p>Own services.</p>"), LIMIT
    )

    assert build_embedding_text(doc) == (
        "Title: Backend Engineer\n"
        "Company: Acme\n"
        "Location: Berlin\n"
        "Seniority: senior\n"
        "Work mode: remote\n"
        "Employment type: full time\n"
        "Experience: 3+ years\n"
        "Skills: Python, PostgreSQL\n"
        "\n"
        "Description:\n"
        "Build APIs.\n"
        "Own services."
    )


def test_job_without_posting_data_is_built_from_canonical_fields_only() -> None:
    doc = build_search_document(JOB, None, None, LIMIT)

    assert not doc.is_empty
    assert build_embedding_text(doc) == "Title: Backend Engineer\nCompany: Acme\nLocation: Berlin"
    assert build_weighted_text(doc).d == ""


def test_posting_with_blank_description_and_no_location() -> None:
    job = JobFields(title="Engineer", company="Acme", location=None)

    doc = build_search_document(job, None, PostingFields("   "), LIMIT)

    assert build_embedding_text(doc) == "Title: Engineer\nCompany: Acme"


def test_unknown_enum_values_and_missing_numbers_are_left_out() -> None:
    data = extraction(seniority="unknown", work_mode="unknown", employment_type="unknown")
    data = data.model_copy(update={"min_years_experience": None, "skills": []})

    text = build_embedding_text(build_search_document(JOB, data, None, LIMIT))

    for label in ("Seniority", "Work mode", "Employment type", "Experience", "Skills"):
        assert label not in text


def test_description_is_cut_at_the_limit_and_html_is_removed() -> None:
    posting = PostingFields("<div>" + "word " * 200 + "</div>")

    doc = build_search_document(JOB, None, posting, 50)

    assert len(doc.description) <= 50
    assert "<" not in doc.description
    assert doc.description == ("word " * 10).rstrip()


def test_canonical_fields_are_whitespace_collapsed_and_bounded() -> None:
    job = JobFields(title="  Backend \n Engineer ", company="A" * 1000, location=" \t ")

    doc = build_search_document(job, None, None, LIMIT)

    assert doc.title == "Backend Engineer"
    assert len(doc.company) == 200
    assert doc.location is None


def test_document_with_no_text_is_empty() -> None:
    doc = build_search_document(JobFields(" ", " ", None), None, None, LIMIT)

    assert doc.is_empty


def test_non_english_text_is_kept_as_is() -> None:
    job = JobFields(title="Systemutvecklare", company="Företaget AB", location="Malmö")
    posting = PostingFields("<p>বাংলাদেশে কাজ করুন</p>")

    doc = build_search_document(job, None, posting, LIMIT)

    assert "Malmö" in build_embedding_text(doc)
    assert doc.description == "বাংলাদেশে কাজ করুন"


def test_weighted_text_assigns_fields_to_classes() -> None:
    doc = build_search_document(JOB, extraction(), PostingFields("<p>Build APIs.</p>"), LIMIT)

    weighted = build_weighted_text(doc)

    assert weighted.a == "Backend Engineer"
    assert weighted.b == "Acme Python PostgreSQL senior remote full time"
    assert weighted.c == "Berlin"
    assert weighted.d == "Build APIs."


def test_builders_are_deterministic_and_do_not_mutate_their_inputs() -> None:
    data = extraction()
    before = data.model_dump()

    first = build_search_document(JOB, data, PostingFields("<p>x</p>"), LIMIT)
    second = build_search_document(JOB, data, PostingFields("<p>x</p>"), LIMIT)

    assert first == second
    assert data.model_dump() == before
    assert search_hash(first) == search_hash(second)


def test_search_hash_changes_with_any_searchable_field() -> None:
    base = search_hash(build_search_document(JOB, extraction(), PostingFields("a"), LIMIT))
    other_title = JobFields("Frontend Engineer", "Acme", "Berlin")

    assert base != search_hash(build_search_document(other_title, extraction(), None, LIMIT))
    assert base != search_hash(
        build_search_document(JOB, extraction(skills=["Go"]), PostingFields("a"), LIMIT)
    )
    assert base != search_hash(build_search_document(JOB, extraction(), PostingFields("b"), LIMIT))
    assert base != search_hash(build_search_document(JOB, None, PostingFields("a"), LIMIT))


def test_search_hash_ignores_fields_that_are_not_searched() -> None:
    base = search_hash(build_search_document(JOB, extraction(), None, LIMIT))
    other = search_hash(build_search_document(JOB, extraction(city="Hamburg"), None, LIMIT))

    assert base == other


def test_embedding_hash_depends_on_text_model_version_and_dimension() -> None:
    base = embedding_hash("text", "model", "1", 768)

    assert base == embedding_hash("text", "model", "1", 768)
    assert base != embedding_hash("other", "model", "1", 768)
    assert base != embedding_hash("text", "model-b", "1", 768)
    assert base != embedding_hash("text", "model", "2", 768)
    assert base != embedding_hash("text", "model", "1", 1536)


def test_hash_parts_cannot_run_into_each_other() -> None:
    assert embedding_hash("a", "bc", "1", 768) != embedding_hash("ab", "c", "1", 768)


def test_format_version_is_part_of_both_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = build_search_document(JOB, None, None, LIMIT)
    before = (search_hash(doc), embedding_hash("t", "m", "1", 768))

    monkeypatch.setattr(document, "DOCUMENT_FORMAT_VERSION", DOCUMENT_FORMAT_VERSION + 1)

    assert search_hash(doc) != before[0]
    assert embedding_hash("t", "m", "1", 768) != before[1]
