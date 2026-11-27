"""What is read from a CV: the fields of a career profile.

`CvExtraction` is the schema the language model must answer with. It is lenient on purpose: dates
are text, every field may be empty, and the validators only clean, bound and drop. When the answer
does not fit, the model is asked to correct it (the repair loop). `to_proposal` then turns the
answer into a `CvProposal`, which is built from the same strict models a career profile is saved
with, so a client can put it straight into the editors. An entry that cannot be saved as it stands
(an experience without a start month, a language without a stated level) is left out rather than
completed with a guess, and a field the CV does not state stays empty.
"""

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from sanket.career import schemas
from sanket.career.fields import MIN_YEAR, format_month, parse_month, this_month

# Bumped when the fields or the rules change.
CV_SCHEMA_VERSION = 2

_CURRENT = frozenset({"present", "current", "now", "ongoing", "today", "to date"})
_YEAR = re.compile(r"^\d{4}$")
_YEAR_MONTH = re.compile(r"^\d{4}-\d{1,2}$")


def _text(value: Any) -> Any:
    """Whitespace collapsed; anything but text is left for validation."""
    if isinstance(value, str):
        return " ".join(value.replace("\x00", "").split())
    return value


def _block(value: Any) -> Any:
    if isinstance(value, str):
        return schemas.clean_block(value.replace("\x00", ""))
    return value


Line = Annotated[str, BeforeValidator(_text)]
Block = Annotated[str, BeforeValidator(_block)]


def _clipped(max_items: int) -> BeforeValidator:
    """Lists longer than the career profile allows are cut, not refused."""

    def clip(value: Any) -> Any:
        return value[:max_items] if isinstance(value, list) else value

    return BeforeValidator(clip)


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CvPersonal(_Lenient):
    full_name: Line = Field(default="", description="The person's name as written, or empty.")
    headline: Line = Field(default="", description="The professional headline the CV states.")
    summary: Block = Field(
        default="", description="The CV's own short profile or summary, condensed, or empty."
    )
    country: Line = Field(
        default="",
        description="ISO 3166-1 alpha-2 code of the country where the CV says the person is based.",
    )
    city: Line = Field(default="", description="The city where the CV says the person is based.")
    github_url: Line = Field(default="", description="The GitHub address the CV prints, or empty.")
    linkedin_url: Line = Field(
        default="", description="The LinkedIn address the CV prints, or empty."
    )
    portfolio_url: Line = Field(default="", description="A personal website or portfolio address.")


class CvEducation(_Lenient):
    institution: Line = ""
    degree: Line = ""
    field: Line = Field(default="", description="The field of study.")
    start: Line = Field(default="", description="YYYY-MM; a year alone as YYYY-01.")
    end: Line = Field(default="", description="YYYY-MM; empty while ongoing or if not stated.")
    grade: Line = Field(default="", description="Only if the CV states one.")


class CvExperience(_Lenient):
    company: Line = ""
    title: Line = ""
    start: Line = Field(default="", description="YYYY-MM; a year alone as YYYY-01.")
    end: Line = Field(default="", description="YYYY-MM; empty if the job is current.")
    current: bool = Field(default=False, description="True only if the CV says the job is current.")
    description: Block = Field(
        default="", description="What the CV says about the work, condensed."
    )


class CvSkill(_Lenient):
    name: Line = ""
    level: schemas.SkillLevel | None = Field(
        default=None, description="Only if the CV states a level for this skill."
    )


class CvLanguage(_Lenient):
    name: Line = Field(default="", description="A spoken language, such as English.")
    proficiency: schemas.Proficiency | None = Field(
        default=None, description="How well the CV says the person speaks it."
    )


class CvCertification(_Lenient):
    title: Line = ""
    issuer: Line = ""
    year: int | str | None = None
    url: Line = ""


class CvProject(_Lenient):
    title: Line = ""
    description: Block = ""
    url: Line = ""


class CvExtraction(_Lenient):
    """The answer of the model. Nothing in it is saved."""

    personal: CvPersonal = Field(default_factory=CvPersonal)
    education: Annotated[list[CvEducation], _clipped(schemas.MAX_EDUCATION)] = Field(
        default_factory=list
    )
    experience: Annotated[list[CvExperience], _clipped(schemas.MAX_EXPERIENCE)] = Field(
        default_factory=list
    )
    skills: Annotated[list[CvSkill], _clipped(schemas.MAX_SKILLS)] = Field(default_factory=list)
    languages: Annotated[list[CvLanguage], _clipped(schemas.MAX_LANGUAGES)] = Field(
        default_factory=list
    )
    certifications: Annotated[list[CvCertification], _clipped(schemas.MAX_CERTIFICATIONS)] = Field(
        default_factory=list
    )
    projects: Annotated[list[CvProject], _clipped(schemas.MAX_PROJECTS)] = Field(
        default_factory=list
    )


# --- the proposal: strict models, what a client receives ---------------------------------------


class CvPersonalProposal(BaseModel):
    full_name: str = ""
    headline: str = ""
    summary: str = ""
    country: str = ""
    city: str = ""
    github_url: str = ""
    linkedin_url: str = ""
    portfolio_url: str = ""


class CvProposal(BaseModel):
    """A career profile read from a CV, for review. Every part may be empty."""

    personal: CvPersonalProposal
    education: list[schemas.EducationWrite]
    experience: list[schemas.ExperienceWrite]
    skills: list[schemas.SkillWrite]
    languages: list[schemas.LanguageWrite]
    certifications: list[schemas.CertificationWrite]
    projects: list[schemas.ProjectWrite]


def _month(value: str) -> str | None:
    """`YYYY-MM` for a month the CV gave, `YYYY-01` for a year alone, None for anything else."""
    text = value.strip()
    if _YEAR.match(text):
        text = f"{text}-01"
    elif _YEAR_MONTH.match(text):
        year, month = text.split("-")
        text = f"{year}-{int(month):02d}"
    else:
        return None
    try:
        return format_month(parse_month(text))  # type: ignore[arg-type]
    except ValueError:
        return None


def _valid(model: type[BaseModel], values: dict[str, Any]) -> Any | None:
    """The strict model built from `values`, or None when it cannot be saved as it stands."""
    try:
        return model.model_validate(values)
    except ValidationError:
        return None


def _personal(person: CvPersonal) -> CvPersonalProposal:
    """Each field kept only if it passes the career profile's own rules (a bad link or country
    code is left out, not repaired)."""
    kept: dict[str, str] = {}
    for name, value in person.model_dump().items():
        built = _valid(schemas.PersonalWrite, {name: value})
        kept[name] = getattr(built, name) if built is not None else ""
    return CvPersonalProposal(**kept)


def _education(items: list[CvEducation]) -> list[schemas.EducationWrite]:
    entries = []
    for item in items:
        start, end = _month(item.start), _month(item.end)
        entry = _valid(
            schemas.EducationWrite,
            {
                "institution": item.institution,
                "degree": item.degree,
                "field": item.field,
                "start": start,
                "end": end,
                "grade": item.grade,
            },
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _experience(items: list[CvExperience]) -> list[schemas.ExperienceWrite]:
    entries = []
    for item in items:
        current = item.current or item.end.strip().casefold() in _CURRENT
        entry = _valid(
            schemas.ExperienceWrite,
            {
                "company": item.company,
                "title": item.title,
                "start": _month(item.start),
                "current": current,
                "end": None if current else _month(item.end),
                "description": item.description,
            },
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _named(items: list[Any], model: type[BaseModel], build: Any) -> list[Any]:
    """Entries that pass `model`, without a second one of the same name (ignoring case)."""
    seen: set[str] = set()
    entries = []
    for item in items:
        entry = _valid(model, build(item))
        if entry is None or entry.name.casefold() in seen:
            continue
        seen.add(entry.name.casefold())
        entries.append(entry)
    return entries


def _year(value: int | str | None) -> int | None:
    """The year a certification was earned, or None if the CV gave none that makes sense."""
    text = str(value).strip() if value is not None else ""
    if not _YEAR.match(text):
        return None
    year = int(text)
    return year if MIN_YEAR <= year <= this_month().year + 1 else None


def to_proposal(extraction: CvExtraction) -> CvProposal:
    """The strict proposal for an answer that fit the schema."""
    certifications = [
        _valid(
            schemas.CertificationWrite,
            {
                "title": item.title,
                "issuer": item.issuer,
                "year": _year(item.year),
                "url": item.url,
            },
        )
        for item in extraction.certifications
    ]
    projects = [
        _valid(
            schemas.ProjectWrite,
            {"title": item.title, "description": item.description, "url": item.url},
        )
        for item in extraction.projects
    ]
    return CvProposal(
        personal=_personal(extraction.personal),
        education=_education(extraction.education),
        experience=_experience(extraction.experience),
        skills=_named(
            extraction.skills,
            schemas.SkillWrite,
            lambda item: {"name": item.name, "level": item.level},
        ),
        languages=_named(
            [item for item in extraction.languages if item.proficiency is not None],
            schemas.LanguageWrite,
            lambda item: {"name": item.name, "proficiency": item.proficiency},
        ),
        certifications=[entry for entry in certifications if entry is not None],
        projects=[entry for entry in projects if entry is not None],
    )
