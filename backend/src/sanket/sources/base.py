from datetime import date

from pydantic import AwareDatetime, BaseModel


class NormalizedPosting(BaseModel):
    source: str
    source_id: str
    url: str
    title: str
    raw: dict
    company: str | None = None
    location: str | None = None
    description: str | None = None
    salary_text: str | None = None
    published_at: AwareDatetime | None = None
    deadline: date | None = None
