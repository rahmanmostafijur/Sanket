"""The text of a profile that is embedded, and the hashes that gate embedding and matching.

Pure functions: the same criteria always give the same text and hashes, which is what lets
the worker skip an embedding call when nothing that matters changed.

Embedding text, one line per field that is set, in this order::

    Looking for: <summary>
    Desired titles: <title>; <title>
    Required skills: <skill>, <skill>
    Preferred skills: <skill>, <skill>
    Seniority: <junior, mid>
    Work mode: <remote, hybrid>
    Employment type: <full time>
    Countries: <DE, SE>
    Locations: <Berlin; Stockholm>

The name is a label and is not embedded. The profile is embedded as a *query*
(`embed_query`, RETRIEVAL_QUERY): it states a need that is compared with job *documents*
(RETRIEVAL_DOCUMENT), which is the asymmetric pairing the embedding model is trained for.
Changing the format changes every hash, so every profile is embedded again; bump
`PROFILE_FORMAT_VERSION` when it changes on purpose.
"""

import hashlib
import json
from typing import Any

from sanket.profiles.criteria import ProfileCriteria

PROFILE_FORMAT_VERSION = 1
# Embedded as a query; part of the hash so a change of task type re-embeds.
EMBEDDING_TASK = "query"


def _label(value: Any) -> str:
    return str(getattr(value, "value", value)).replace("_", " ")


def build_profile_text(criteria: ProfileCriteria) -> str:
    """The text sent to the embedding model (format in the module docstring)."""
    lines = [
        ("Looking for", criteria.summary),
        ("Desired titles", "; ".join(criteria.desired_titles)),
        ("Required skills", ", ".join(criteria.required_skills)),
        ("Preferred skills", ", ".join(criteria.preferred_skills)),
        ("Seniority", ", ".join(_label(level) for level in criteria.seniorities)),
        ("Work mode", ", ".join(_label(mode) for mode in criteria.work_modes)),
        ("Employment type", ", ".join(_label(kind) for kind in criteria.employment_types)),
        ("Countries", ", ".join(criteria.countries)),
        ("Locations", "; ".join(criteria.locations)),
    ]
    return "\n".join(f"{name}: {value}" for name, value in lines if value)


def _digest(parts: list[object]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_criteria(criteria: ProfileCriteria) -> dict[str, Any]:
    """The criteria as JSON-ready data with every list in a fixed order, so two profiles that
    say the same thing in a different order are equal."""
    data: dict[str, Any] = criteria.model_dump(mode="json")
    for name, value in data.items():
        if isinstance(value, list):
            data[name] = sorted(value, key=str.casefold)
    return data


def content_hash(criteria: ProfileCriteria, active: bool) -> str:
    """Hash of everything that decides what a profile matches: the criteria and `active`.

    The name is a label and is not part of it, so renaming re-embeds and re-matches nothing.
    """
    return _digest([PROFILE_FORMAT_VERSION, canonical_criteria(criteria), active])


def profile_embedding_hash(text: str, model_name: str, model_version: str, dimension: int) -> str:
    """Hash of everything a stored profile embedding depends on."""
    return _digest(
        [PROFILE_FORMAT_VERSION, EMBEDDING_TASK, model_name, model_version, dimension, text]
    )
