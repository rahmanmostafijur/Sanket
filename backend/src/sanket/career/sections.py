"""The list sections of the career profile: which table each is, how an item becomes a row and a
row becomes an item, how many entries it may hold and in what order they are shown.

The store and the router are written once, against `SectionSpec`; adding a section means adding
a spec here (and its table and schemas).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import desc

from sanket.career import schemas
from sanket.models import (
    Base,
    CareerCertification,
    CareerEducation,
    CareerExperience,
    CareerLanguage,
    CareerProject,
    CareerSkill,
)

W = TypeVar("W", bound=BaseModel)
O = TypeVar("O", bound=BaseModel)


@dataclass(frozen=True)
class SectionSpec(Generic[W, O]):
    name: str
    table: type[Base]
    write: type[W]
    out: type[O]
    # The body of "replace the whole section": `{"items": [...]}`.
    items: type[BaseModel]
    max_items: int
    order: tuple[Any, ...]
    to_values: Callable[[W], dict[str, Any]]
    to_out: Callable[[Any], O]
    # What a client is told when two entries of the section clash (skills and languages).
    duplicate_message: str = "this entry is already in the list"


def _text(value: str) -> str | None:
    """Empty text is stored as null."""
    return value or None


def _education_values(item: schemas.EducationWrite) -> dict[str, Any]:
    return {
        "institution": item.institution,
        "degree": _text(item.degree),
        "field": _text(item.field),
        "start_date": item.start,
        "end_date": item.end,
        "grade": _text(item.grade),
    }


def _education_out(row: Any) -> schemas.EducationOut:
    return schemas.EducationOut(
        id=row.id,
        institution=row.institution,
        degree=row.degree or "",
        field=row.field or "",
        start=row.start_date,
        end=row.end_date,
        grade=row.grade or "",
    )


def _experience_values(item: schemas.ExperienceWrite) -> dict[str, Any]:
    return {
        "company": item.company,
        "title": item.title,
        "start_date": item.start,
        "end_date": item.end,
        "is_current": item.current,
        "description": _text(item.description),
    }


def _experience_out(row: Any) -> schemas.ExperienceOut:
    return schemas.ExperienceOut(
        id=row.id,
        company=row.company,
        title=row.title,
        start=row.start_date,
        current=row.is_current,
        end=row.end_date,
        description=row.description or "",
    )


def _skill_values(item: schemas.SkillWrite) -> dict[str, Any]:
    return {"name": item.name, "level": item.level}


def _skill_out(row: Any) -> schemas.SkillOut:
    return schemas.SkillOut(id=row.id, name=row.name, level=row.level)


def _language_values(item: schemas.LanguageWrite) -> dict[str, Any]:
    return {"name": item.name, "proficiency": item.proficiency}


def _language_out(row: Any) -> schemas.LanguageOut:
    return schemas.LanguageOut(id=row.id, name=row.name, proficiency=row.proficiency)


def _certification_values(item: schemas.CertificationWrite) -> dict[str, Any]:
    return {
        "title": item.title,
        "issuer": _text(item.issuer),
        "year": item.year,
        "url": _text(item.url),
    }


def _certification_out(row: Any) -> schemas.CertificationOut:
    return schemas.CertificationOut(
        id=row.id, title=row.title, issuer=row.issuer or "", year=row.year, url=row.url or ""
    )


def _project_values(item: schemas.ProjectWrite) -> dict[str, Any]:
    return {"title": item.title, "description": _text(item.description), "url": _text(item.url)}


def _project_out(row: Any) -> schemas.ProjectOut:
    return schemas.ProjectOut(
        id=row.id, title=row.title, description=row.description or "", url=row.url or ""
    )


EDUCATION = SectionSpec(
    name="education",
    table=CareerEducation,
    write=schemas.EducationWrite,
    out=schemas.EducationOut,
    items=schemas.EducationItems,
    max_items=schemas.MAX_EDUCATION,
    order=(desc(CareerEducation.start_date), CareerEducation.id),
    to_values=_education_values,
    to_out=_education_out,
)
EXPERIENCE = SectionSpec(
    name="experience",
    table=CareerExperience,
    write=schemas.ExperienceWrite,
    out=schemas.ExperienceOut,
    items=schemas.ExperienceItems,
    max_items=schemas.MAX_EXPERIENCE,
    order=(desc(CareerExperience.start_date), CareerExperience.id),
    to_values=_experience_values,
    to_out=_experience_out,
)
SKILLS = SectionSpec(
    name="skills",
    table=CareerSkill,
    write=schemas.SkillWrite,
    out=schemas.SkillOut,
    items=schemas.SkillItems,
    max_items=schemas.MAX_SKILLS,
    order=(CareerSkill.id,),
    to_values=_skill_values,
    to_out=_skill_out,
    duplicate_message="this skill is already in the list",
)
LANGUAGES = SectionSpec(
    name="languages",
    table=CareerLanguage,
    write=schemas.LanguageWrite,
    out=schemas.LanguageOut,
    items=schemas.LanguageItems,
    max_items=schemas.MAX_LANGUAGES,
    order=(CareerLanguage.id,),
    to_values=_language_values,
    to_out=_language_out,
    duplicate_message="this language is already in the list",
)
CERTIFICATIONS = SectionSpec(
    name="certifications",
    table=CareerCertification,
    write=schemas.CertificationWrite,
    out=schemas.CertificationOut,
    items=schemas.CertificationItems,
    max_items=schemas.MAX_CERTIFICATIONS,
    order=(CareerCertification.id,),
    to_values=_certification_values,
    to_out=_certification_out,
)
PROJECTS = SectionSpec(
    name="projects",
    table=CareerProject,
    write=schemas.ProjectWrite,
    out=schemas.ProjectOut,
    items=schemas.ProjectItems,
    max_items=schemas.MAX_PROJECTS,
    order=(CareerProject.id,),
    to_values=_project_values,
    to_out=_project_out,
)

ALL_SECTIONS = (EDUCATION, EXPERIENCE, SKILLS, LANGUAGES, CERTIFICATIONS, PROJECTS)
