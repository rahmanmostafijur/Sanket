"""How each source is named and credited next to its jobs (docs/sources.md has the rules).

Every result links to the original listing (`url`) and names its source. Where the provider's
terms ask for credit (Remote OK, Remotive and others), `attribution` carries the sentence to
show; sources that ask for none (employer boards) have `attribution` null, but are still
named and linked.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceInfo:
    name: str
    # Text to show next to the job, or None when the source asks for no credit.
    attribution: str | None


SOURCE_INFO: dict[str, SourceInfo] = {
    "remoteok": SourceInfo("Remote OK", "Job listing from Remote OK"),
    "remotive": SourceInfo("Remotive", "Job listing from Remotive"),
    "weworkremotely": SourceInfo("We Work Remotely", "Job listing from We Work Remotely"),
    "jobicy": SourceInfo("Jobicy", "Job listing from Jobicy"),
    "himalayas": SourceInfo("Himalayas", "Job listing from Himalayas"),
    "usajobs": SourceInfo("USAJOBS", "Job listing from USAJOBS"),
    "jobtech_se": SourceInfo("JobTech Sweden", "Job listing from Arbetsformedlingen (Platsbanken)"),
    "greenhouse": SourceInfo("Greenhouse", None),
    "lever": SourceInfo("Lever", None),
    "ashby": SourceInfo("Ashby", None),
}


def source_info(source: str) -> SourceInfo:
    """Display name and credit text; an unknown source is named by its identifier."""
    return SOURCE_INFO.get(source, SourceInfo(source, None))
