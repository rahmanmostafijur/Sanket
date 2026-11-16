"""The source registry: every adapter is built from settings and can be selected by name."""

import pytest
from pydantic import SecretStr

from sanket.config import Settings
from sanket.ingest import build_sources, select_sources
from sanket.sources.ashby import AshbySource
from sanket.sources.jobtech_se import JobTechSource
from sanket.sources.usajobs import UsaJobsSource

NEW_SOURCES = ["ashby", "jobtech_se", "usajobs"]


def make_settings(**values: object) -> Settings:
    # model_validate does not read the environment, so a developer's own .env stays out.
    return Settings.model_validate({"database_url": "postgresql://x/y_test", **values})


def test_registry_contains_every_source_once() -> None:
    names = [source.name for source in build_sources(make_settings())]

    assert names == [
        "remoteok",
        "remotive",
        "weworkremotely",
        "jobicy",
        "himalayas",
        "greenhouse",
        "lever",
        "ashby",
        "usajobs",
        "jobtech_se",
    ]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("name", NEW_SOURCES)
def test_select_sources_accepts_the_new_source_names(name: str) -> None:
    sources = build_sources(make_settings())

    assert [source.name for source in select_sources(sources, [name])] == [name]


def test_select_sources_still_rejects_unknown_names() -> None:
    with pytest.raises(SystemExit, match="Unknown INGEST_SOURCES: nope"):
        select_sources(build_sources(make_settings()), ["ashby", "nope"])


def test_registry_passes_the_settings_to_the_new_sources() -> None:
    config = make_settings(
        ashby_boards="acme, other",
        jobtech_query="python",
        jobtech_max_pages=3,
        jobtech_lookback_days=1,
        usajobs_api_key="secret",
        usajobs_user_agent_email="me@example.com",
    )

    sources = {source.name: source for source in build_sources(config)}

    ashby, jobtech, usajobs = sources["ashby"], sources["jobtech_se"], sources["usajobs"]
    assert isinstance(ashby, AshbySource)
    assert ashby.boards == ["acme", "other"]
    assert isinstance(jobtech, JobTechSource)
    assert (jobtech.query, jobtech.max_pages) == ("python", 3)
    assert jobtech.lookback.days == 1
    assert isinstance(usajobs, UsaJobsSource)
    assert usajobs.api_key == SecretStr("secret")
    assert usajobs.user_agent_email == "me@example.com"


def test_blank_settings_from_an_unset_ci_variable_mean_not_configured() -> None:
    config = make_settings(
        ashby_boards="", jobtech_query="", usajobs_api_key="", usajobs_user_agent_email=""
    )

    assert config.ashby_boards == []
    assert config.jobtech_query is None
    assert config.usajobs_api_key is None
    assert config.usajobs_user_agent_email is None


def test_jobtech_settings_have_small_bounds() -> None:
    config = make_settings()

    assert (config.jobtech_max_pages, config.jobtech_lookback_days) == (5, 2)
    with pytest.raises(ValueError):
        make_settings(jobtech_max_pages=21)
    with pytest.raises(ValueError):
        make_settings(jobtech_max_pages=0)
