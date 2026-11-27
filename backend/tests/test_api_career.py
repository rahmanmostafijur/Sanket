"""The career profile through the API: sections, validation, privacy between accounts, the draft."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.auth_helpers import API_KEY, auth_client, bearer
from tests.test_api_accounts import BOB, headers_of, scalar, sign_up
from tests.test_api_profiles import BODY

TABLE_OF = {
    "education": "career_education",
    "experience": "career_experience",
    "skills": "career_skill",
    "languages": "career_language",
    "certifications": "career_certification",
    "projects": "career_project",
}
CAREER_TABLES = ("career_profile", *TABLE_OF.values())

# One valid entry per section, every field given, and a different one to change it to.
SECTIONS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "education": (
        {
            "institution": "Example University",
            "degree": "BSc",
            "field": "Computer Science",
            "start": "2012-09",
            "end": "2016-06",
            "grade": "1.7",
        },
        {
            "institution": "Sample College",
            "degree": "MSc",
            "field": "Data Science",
            "start": "2016-09",
            "end": None,
            "grade": "",
        },
    ),
    "experience": (
        {
            "company": "Example Corp",
            "title": "Backend Engineer",
            "start": "2019-01",
            "current": True,
            "end": None,
            "description": "Built APIs.\n\nLed a small team.",
        },
        {
            "company": "Sample GmbH",
            "title": "Developer",
            "start": "2015-03",
            "current": False,
            "end": "2018-12",
            "description": "",
        },
    ),
    "skills": (
        {"name": "Python", "level": "expert"},
        {"name": "Go", "level": None},
    ),
    "languages": (
        {"name": "English", "proficiency": "fluent"},
        {"name": "German", "proficiency": "basic"},
    ),
    "certifications": (
        {
            "title": "Cloud Practitioner",
            "issuer": "Example Cloud",
            "year": 2022,
            "url": "https://example.com/cert",
        },
        {"title": "Data Exam", "issuer": "", "year": None, "url": ""},
    ),
    "projects": (
        {
            "title": "Router",
            "description": "An open-source HTTP router.",
            "url": "https://github.com/ada-example/router",
        },
        {"title": "Notes", "description": "", "url": ""},
    ),
}
SECTION_NAMES = list(SECTIONS)

PERSONAL = {
    "full_name": "Ada Example",
    "headline": "Backend engineer",
    "summary": "Builds APIs and data pipelines.",
    "country": "DE",
    "city": "Berlin",
    "github_url": "https://github.com/ada-example",
    "linkedin_url": "https://www.linkedin.com/in/ada-example",
    "portfolio_url": "https://ada.example.com",
    "availability": "open_to_offers",
}


def without_id(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "id"}


def items_of(response: Any) -> list[dict[str, Any]]:
    return [without_id(item) for item in response.json()["items"]]


def account(client: TestClient, email: str = "ada@example.com") -> dict[str, str]:
    return headers_of(sign_up(client, email))


def count(engine: Engine, table: str) -> int:
    return int(scalar(engine, f"select count(*) from {table}"))


def fill_everything(client: TestClient, headers: dict[str, str]) -> None:
    assert client.put("/career/personal", json=PERSONAL, headers=headers).status_code == 200
    for name, (first, _) in SECTIONS.items():
        response = client.put(f"/career/{name}", json={"items": [first]}, headers=headers)
        assert response.status_code == 200, response.text


# --- who may call ----------------------------------------------------------------------------


def career_routes(client: TestClient) -> list[tuple[str, str]]:
    schema = client.get("/openapi.json").json()
    routes: list[tuple[str, str]] = []
    for path, methods in schema["paths"].items():
        if path.startswith("/career"):
            routes.extend((method.upper(), path.replace("{entry_id}", "1")) for method in methods)
    return routes


def test_there_are_career_routes_to_check(clean_db: Engine) -> None:
    routes = career_routes(auth_client(clean_db))

    # The whole profile, the personal details and the draft; five routes for each of six sections.
    assert len(routes) == 3 + 6 * 5
    assert ("GET", "/career") in routes and ("POST", "/career/matching-draft") in routes


def test_every_career_route_needs_a_credential(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    for method, path in career_routes(client):
        response = client.request(method, path, json={})
        assert response.status_code == 401, (method, path)
        assert response.headers["www-authenticate"] == "Bearer"


def test_a_credential_that_is_not_an_account_has_no_career_profile(clean_db: Engine) -> None:
    client = auth_client(clean_db, auth_api_keys=f"svc={API_KEY}")

    for method, path in career_routes(client):
        response = client.request(method, path, json={}, headers=bearer(API_KEY))
        assert response.status_code == 404, (method, path)


def test_nothing_of_a_career_profile_is_reachable_without_signing_in(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    fill_everything(client, account(client))
    paths = client.get("/openapi.json").json()["paths"]

    # No public or shareable page exists, and no export.
    hidden = ("public", "export", "download", "photo")
    assert not [p for p in paths if any(word in p for word in hidden)]
    assert client.get("/career").status_code == 401
    assert client.get("/users/1").status_code == 404


# --- the whole profile -----------------------------------------------------------------------


def test_a_new_account_has_an_empty_profile_not_a_missing_one(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    response = client.get("/career", headers=account(client))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["personal"] == {
        "full_name": "",
        "headline": "",
        "summary": "",
        "country": "",
        "city": "",
        "github_url": "",
        "linkedin_url": "",
        "portfolio_url": "",
        "availability": None,
    }
    for name in SECTION_NAMES:
        assert body[name] == []
    assert body["years_of_experience"] is None
    assert body["completeness"]["percent"] == 0
    assert len(body["completeness"]["missing"]) == 7


def test_the_profile_holds_nothing_beyond_the_agreed_fields(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    fill_everything(client, ada)

    body = client.get("/career", headers=ada).json()

    assert set(body) == {*SECTION_NAMES, "personal", "completeness", "years_of_experience"}
    assert set(body["personal"]) == set(PERSONAL)


def test_completeness_counts_filled_sections_and_names_the_empty_ones(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    client.put("/career/personal", json=PERSONAL, headers=ada)
    for name in ("skills", "experience"):
        client.put(f"/career/{name}", json={"items": [SECTIONS[name][0]]}, headers=ada)

    completeness = client.get("/career", headers=ada).json()["completeness"]

    assert completeness["percent"] == 43
    assert completeness["missing"] == ["education", "languages", "certifications", "projects"]
    assert completeness["sections"]["personal"] is True


def test_a_complete_profile_is_one_hundred_percent(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    fill_everything(client, ada)

    completeness = client.get("/career", headers=ada).json()["completeness"]

    assert (completeness["percent"], completeness["missing"]) == (100, [])


def test_years_of_experience_come_from_the_employment_dates(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    jobs = [
        {"company": "A", "title": "Dev", "start": "2018-01", "end": "2019-12", "current": False},
        {"company": "B", "title": "Dev", "start": "2019-07", "end": "2020-12", "current": False},
    ]

    client.put("/career/experience", json={"items": jobs}, headers=ada)

    assert client.get("/career", headers=ada).json()["years_of_experience"] == 3.0


# --- personal details ------------------------------------------------------------------------


def test_personal_details_are_saved_replaced_and_cleaned(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    given = {
        **PERSONAL,
        "full_name": "  Ada   Example ",
        "country": "de",
        "github_url": "github.com/ada",
    }

    saved = client.put("/career/personal", json=given, headers=ada)

    assert saved.status_code == 200
    assert saved.json()["full_name"] == "Ada Example"
    assert saved.json()["country"] == "DE"
    assert saved.json()["github_url"] == "https://github.com/ada"
    assert client.get("/career", headers=ada).json()["personal"] == saved.json()


def test_putting_personal_details_replaces_all_and_an_omitted_one_is_cleared(
    clean_db: Engine,
) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    client.put("/career/personal", json=PERSONAL, headers=ada)

    client.put("/career/personal", json={"full_name": "Ada Example"}, headers=ada)

    personal = client.get("/career", headers=ada).json()["personal"]
    assert personal["full_name"] == "Ada Example"
    assert (personal["headline"], personal["country"], personal["availability"]) == ("", "", None)
    assert scalar(clean_db, "select headline from career_profile") is None
    assert count(clean_db, "career_profile") == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "n" * 101),
        ("headline", "h" * 121),
        ("summary", "s" * 1001),
        ("city", "c" * 101),
        ("country", "Germany"),
        ("github_url", "https://gitlab.com/ada-example"),
        ("linkedin_url", "ftp://linkedin.com/in/ada"),
        ("portfolio_url", "javascript:alert(1)"),
        ("availability", "whenever"),
    ],
)
def test_an_invalid_personal_detail_is_422_on_its_field_and_changes_nothing(
    clean_db: Engine, field: str, value: str
) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    client.put("/career/personal", json=PERSONAL, headers=ada)

    response = client.put("/career/personal", json={**PERSONAL, field: value}, headers=ada)

    assert response.status_code == 422
    assert [field] == [d["loc"][-1] for d in response.json()["error"]["details"]]
    assert client.get("/career", headers=ada).json()["personal"] == PERSONAL


@pytest.mark.parametrize(
    "name",
    [
        "date_of_birth",
        "gender",
        "religion",
        "marital_status",
        "parents",
        "address",
        "photo",
        "email",
    ],
)
def test_what_must_not_be_collected_is_refused(clean_db: Engine, name: str) -> None:
    client = auth_client(clean_db)

    response = client.put("/career/personal", json={name: "x"}, headers=account(client))

    assert response.status_code == 422


# --- the list sections -----------------------------------------------------------------------


@pytest.mark.parametrize("name", SECTION_NAMES)
def test_a_section_starts_empty_and_an_entry_can_be_added_changed_and_removed(
    clean_db: Engine, name: str
) -> None:
    first, second = SECTIONS[name]
    client = auth_client(clean_db)
    ada = account(client)
    url = f"/career/{name}"
    assert client.get(url, headers=ada).json() == {"items": []}

    created = client.post(url, json=first, headers=ada)
    assert created.status_code == 201
    assert without_id(created.json()) == first
    entry_id = created.json()["id"]
    assert items_of(client.get(url, headers=ada)) == [first]

    changed = client.put(f"{url}/{entry_id}", json=second, headers=ada)
    assert changed.status_code == 200
    assert (changed.json()["id"], without_id(changed.json())) == (entry_id, second)

    assert client.delete(f"{url}/{entry_id}", headers=ada).status_code == 204
    assert client.get(url, headers=ada).json() == {"items": []}
    assert client.delete(f"{url}/{entry_id}", headers=ada).status_code == 404
    assert client.put(f"{url}/{entry_id}", json=second, headers=ada).status_code == 404


@pytest.mark.parametrize("name", SECTION_NAMES)
def test_a_section_is_replaced_whole_and_all_or_nothing(clean_db: Engine, name: str) -> None:
    first, second = SECTIONS[name]
    client = auth_client(clean_db)
    ada = account(client)
    url = f"/career/{name}"
    client.put(url, json={"items": [first]}, headers=ada)

    replaced = client.put(url, json={"items": [second]}, headers=ada)

    assert replaced.status_code == 200
    assert items_of(replaced) == [second]
    assert items_of(client.get(url, headers=ada)) == [second]
    broken = client.put(url, json={"items": [first, {"nonsense": True}]}, headers=ada)
    assert broken.status_code == 422
    assert items_of(client.get(url, headers=ada)) == [second]
    assert client.put(url, json={"items": []}, headers=ada).json() == {"items": []}
    assert count(clean_db, TABLE_OF[name]) == 0


@pytest.mark.parametrize("name", SECTION_NAMES)
def test_a_section_refuses_unknown_fields_and_a_missing_body(clean_db: Engine, name: str) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    first = SECTIONS[name][0]
    url = f"/career/{name}"

    assert client.post(url, json={**first, "photo": "x"}, headers=ada).status_code == 422
    assert client.post(url, json={}, headers=ada).status_code == 422
    assert client.put(url, json={"items": "nope"}, headers=ada).status_code == 422
    assert client.get(url, headers=ada).json() == {"items": []}


def test_the_newest_study_and_job_come_first(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    new, old = SECTIONS["experience"]
    client.put("/career/experience", json={"items": [old, new]}, headers=ada)
    school, college = SECTIONS["education"]
    client.put("/career/education", json={"items": [school, college]}, headers=ada)

    jobs = client.get("/career/experience", headers=ada).json()["items"]
    studies = client.get("/career/education", headers=ada).json()["items"]

    assert [job["company"] for job in jobs] == ["Example Corp", "Sample GmbH"]
    assert [study["institution"] for study in studies] == ["Sample College", "Example University"]


# --- dates and lengths ------------------------------------------------------------------------


def test_a_date_error_names_the_row_and_the_field(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    items = [
        SECTIONS["education"][0],
        {"institution": "X", "start": "2016-01", "end": "2015-01"},
    ]

    response = client.put("/career/education", json={"items": items}, headers=account(client))

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert [d["loc"] for d in details] == [["body", "items", 1, "end"]]
    assert "before the start" in details[0]["msg"]


@pytest.mark.parametrize(
    ("section", "changes", "field"),
    [
        ("education", {"start": "2021-13"}, "start"),
        ("education", {"start": "21-01"}, "start"),
        ("education", {"start": "2999-01"}, "start"),
        ("education", {"institution": "i" * 151}, "institution"),
        ("education", {"degree": "d" * 101}, "degree"),
        ("education", {"grade": "g" * 51}, "grade"),
        ("experience", {"current": True, "end": "2020-01"}, "end"),
        ("experience", {"current": False, "end": None}, "end"),
        ("experience", {"current": False, "end": "2010-01"}, "end"),
        ("experience", {"current": False, "end": "2999-01"}, "end"),
        ("experience", {"company": ""}, "company"),
        ("experience", {"title": "t" * 151}, "title"),
        ("experience", {"description": "d" * 2001}, "description"),
        ("skills", {"name": "s" * 61}, "name"),
        ("skills", {"level": "wizard"}, "level"),
        ("languages", {"proficiency": "godlike"}, "proficiency"),
        ("languages", {"name": "l" * 61}, "name"),
        ("certifications", {"year": 1949}, "year"),
        ("certifications", {"year": 2999}, "year"),
        ("certifications", {"url": "mailto:ada@example.com"}, "url"),
        ("certifications", {"title": "t" * 151}, "title"),
        ("projects", {"description": "d" * 1001}, "description"),
        ("projects", {"url": "https://user:pw@example.com"}, "url"),
    ],
)
def test_strict_limits_and_dates_are_422_on_the_field(
    clean_db: Engine, section: str, changes: dict[str, Any], field: str
) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    entry = {**SECTIONS[section][0], **changes}

    response = client.post(f"/career/{section}", json=entry, headers=ada)

    assert response.status_code == 422
    assert field in [d["loc"][-1] for d in response.json()["error"]["details"]]
    assert client.get(f"/career/{section}", headers=ada).json() == {"items": []}


def test_the_longest_allowed_entries_are_saved(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    job = {
        "company": "c" * 150,
        "title": "t" * 150,
        "start": "2020-01",
        "current": False,
        "end": "2020-02",
        "description": "d" * 2000,
    }

    assert client.post("/career/experience", json=job, headers=account(client)).status_code == 201


# --- names that must be unique, and the most a section may hold ---------------------------------


@pytest.mark.parametrize("name", ["skills", "languages"])
def test_a_skill_or_language_cannot_be_listed_twice_whatever_the_case(
    clean_db: Engine, name: str
) -> None:
    entry, other = SECTIONS[name]
    client = auth_client(clean_db)
    ada = account(client)
    url = f"/career/{name}"
    client.post(url, json=entry, headers=ada)
    second = client.post(url, json=other, headers=ada).json()
    shouted = {**entry, "name": entry["name"].upper()}
    lowered = {**other, "name": entry["name"].lower()}

    assert client.post(url, json=shouted, headers=ada).status_code == 409
    assert client.put(f"{url}/{second['id']}", json=lowered, headers=ada).status_code == 409
    both = {"items": [entry, {**entry, "name": entry["name"].lower()}]}
    assert client.put(url, json=both, headers=ada).status_code == 422
    assert len(client.get(url, headers=ada).json()["items"]) == 2


def test_two_people_may_both_list_the_same_skill(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)

    assert client.post("/career/skills", json={"name": "Python"}, headers=ada).status_code == 201
    assert client.post("/career/skills", json={"name": "python"}, headers=bob).status_code == 201


def test_a_full_section_takes_no_more_entries(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    items = [{"name": f"Skill{n}"} for n in range(60)]
    assert client.put("/career/skills", json={"items": items}, headers=ada).status_code == 200

    full = client.post("/career/skills", json={"name": "One too many"}, headers=ada)
    over = {"items": [*items, {"name": "One too many"}]}
    too_many = client.put("/career/skills", json=over, headers=ada)

    assert full.status_code == 409
    assert "at most 60" in full.json()["error"]["message"]
    assert too_many.status_code == 422
    assert len(client.get("/career/skills", headers=ada).json()["items"]) == 60


# --- one account can never read or change another's -------------------------------------------


def test_one_account_cannot_read_another_accounts_career_profile(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    fill_everything(client, ada)

    seen = client.get("/career", headers=bob).json()

    assert seen["personal"]["full_name"] == ""
    assert all(seen[name] == [] for name in SECTION_NAMES)
    assert seen["completeness"]["percent"] == 0
    for name in SECTION_NAMES:
        assert client.get(f"/career/{name}", headers=bob).json() == {"items": []}
    assert client.get("/me", headers=bob).json()["full_name"] == ""


@pytest.mark.parametrize("name", SECTION_NAMES)
def test_one_account_cannot_change_or_remove_another_accounts_entry(
    clean_db: Engine, name: str
) -> None:
    first, second = SECTIONS[name]
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    entry_id = client.post(f"/career/{name}", json=first, headers=ada).json()["id"]
    url = f"/career/{name}/{entry_id}"

    assert client.put(url, json=second, headers=bob).status_code == 404
    assert client.delete(url, headers=bob).status_code == 404
    assert items_of(client.get(f"/career/{name}", headers=ada)) == [first]


@pytest.mark.parametrize("name", SECTION_NAMES)
def test_replacing_a_section_replaces_only_your_own(clean_db: Engine, name: str) -> None:
    first, second = SECTIONS[name]
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    client.put(f"/career/{name}", json={"items": [first]}, headers=ada)

    client.put(f"/career/{name}", json={"items": [second]}, headers=bob)
    client.put(f"/career/{name}", json={"items": []}, headers=bob)

    assert items_of(client.get(f"/career/{name}", headers=ada)) == [first]


def test_one_account_cannot_change_another_accounts_personal_details(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    client.put("/career/personal", json=PERSONAL, headers=ada)

    client.put("/career/personal", json={"full_name": "Bob Example"}, headers=bob)

    assert client.get("/career", headers=ada).json()["personal"] == PERSONAL
    assert client.get("/me", headers=ada).json()["full_name"] == "Ada Example"


def test_an_entry_id_of_another_account_is_not_a_way_to_probe_it(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    entry_id = client.post("/career/skills", json={"name": "Python"}, headers=ada).json()["id"]

    missing = client.delete("/career/skills/999999", headers=bob)
    theirs = client.delete(f"/career/skills/{entry_id}", headers=bob)

    assert missing.status_code == theirs.status_code == 404
    assert missing.json()["error"]["message"] == theirs.json()["error"]["message"]


# --- accounts that go away ------------------------------------------------------------------------


def test_deleting_an_account_deletes_its_whole_career_profile(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    fill_everything(client, ada)
    fill_everything(client, bob)

    with clean_db.begin() as conn:
        conn.execute(text("delete from users where email = 'ada@example.com'"))

    assert [count(clean_db, table) for table in CAREER_TABLES] == [1] * len(CAREER_TABLES)
    assert client.get("/career", headers=bob).json()["personal"]["full_name"] == "Ada Example"


def test_a_token_of_a_deleted_account_cannot_write(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    with clean_db.begin() as conn:
        conn.execute(text("delete from users"))

    assert client.put("/career/personal", json=PERSONAL, headers=ada).status_code == 401
    assert client.post("/career/skills", json={"name": "Python"}, headers=ada).status_code == 401


# --- the matching profile draft ------------------------------------------------------------------


def test_nothing_to_derive_from_an_empty_career_profile_is_422(clean_db: Engine) -> None:
    client = auth_client(clean_db)

    response = client.post("/career/matching-draft", headers=account(client))

    assert response.status_code == 422
    assert "add a job or a skill" in response.json()["error"]["message"]


def test_a_draft_is_proposed_from_the_career_profile_and_nothing_is_saved(
    clean_db: Engine,
) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    client.put("/career/personal", json=PERSONAL, headers=ada)
    jobs = [
        {
            "company": "A",
            "title": "Developer",
            "start": "2016-01",
            "end": "2019-12",
            "current": False,
        },
        {"company": "B", "title": "Senior Developer", "start": "2020-01", "current": True},
    ]
    client.put("/career/experience", json={"items": jobs}, headers=ada)
    skills = [
        {"name": "Python", "level": "expert"},
        {"name": "Docker"},
        {"name": "Excel", "level": "beginner"},
    ]
    client.put("/career/skills", json={"items": skills}, headers=ada)
    tables = ("profile", "profile_embedding", "job_match", "saved_job")
    before = {table: count(clean_db, table) for table in tables}

    response = client.post("/career/matching-draft", headers=ada)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    draft = response.json()
    assert draft["desired_titles"] == ["Senior Developer", "Developer"]
    assert draft["required_skills"] == ["Python"]
    assert draft["preferred_skills"] == ["Docker", "Excel"]
    assert draft["seniorities"] == ["senior"]
    assert draft["locations"] == ["Berlin"]
    assert draft["years_of_experience"] >= 10
    assert {table: count(clean_db, table) for table in tables} == before
    assert client.get("/profiles", headers=ada).json()["items"] == []


def test_the_draft_becomes_a_matching_profile_only_when_the_user_saves_it(
    clean_db: Engine,
) -> None:
    client = auth_client(clean_db)
    ada = account(client)
    skills = {"items": [{"name": "Python", "level": "expert"}]}
    client.put("/career/skills", json=skills, headers=ada)
    draft = client.post("/career/matching-draft", headers=ada).json()
    assert client.get("/profiles", headers=ada).json()["items"] == []

    body = {
        **BODY,
        "name": "From my career",
        "desired_titles": draft["desired_titles"] or ["Developer"],
        "required_skills": draft["required_skills"],
        "preferred_skills": draft["preferred_skills"],
        "locations": draft["locations"],
    }
    created = client.post("/profiles", json=body, headers=ada)

    assert created.status_code == 201
    assert created.json()["required_skills"] == ["Python"]


def test_each_accounts_draft_uses_only_its_own_career_profile(clean_db: Engine) -> None:
    client = auth_client(clean_db)
    ada, bob = account(client), account(client, BOB)
    skills = {"items": [{"name": "Python", "level": "expert"}]}
    client.put("/career/skills", json=skills, headers=ada)

    assert client.post("/career/matching-draft", headers=bob).status_code == 422
    assert client.post("/career/matching-draft", headers=ada).json()["required_skills"] == [
        "Python"
    ]
