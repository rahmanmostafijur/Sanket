# Job sources

Which sources feed Sanket, on what terms, and which were considered and
skipped. The rules that decide this are in
[ADR 0001](adr/0001-source-admission-policy.md). Terms below were read on
2026-11-17 unless a row says otherwise; they change, so re-read a provider's
terms before relying on this page.

Every posting keeps a link to its original listing. Where a provider asks for
credit, the source is named as the origin of its data.

## Admitted sources

| Source (`name`) | Endpoint | Auth | Rate and budget | Terms and attribution | Sent to the LLM | Status |
|---|---|---|---|---|---|---|
| Remote OK (`remoteok`) | `https://remoteok.com/api` | none | 12 requests a day | Link back (do-follow) to the Remote OK job URL and name Remote OK as the source; no logo. Its robots.txt reserves AI training (`ai-train=no`). | **No**: listed in `EXTRACTION_EXCLUDED_SOURCES` (default `remoteok`) | active |
| Remotive (`remotive`) | `https://remotive.com/api/remote-jobs` | none | 4 requests a day, one attempt per run (no retries, so a retry cannot exceed the limit) | Link back to the Remotive URL and credit Remotive. Do not pass jobs on to other job sites or gate them behind sign-ups. | yes | active |
| We Work Remotely (`weworkremotely`) | `https://weworkremotely.com/remote-jobs.rss` | none | 12 requests a day | Link back to We Work Remotely. | yes | active |
| Jobicy (`jobicy`) | `https://jobicy.com/api/jobs` | none | 60 requests a day, at most one pass an hour | Credit Jobicy with a link, keep apply links on the Jobicy URL, mark closed jobs as unavailable when shown. Storage and AI analysis are allowed. | yes | active |
| Himalayas (`himalayas`) | `https://himalayas.app/jobs/api` | optional bearer key (`HIMALAYAS_API_KEY`) | about 60 requests a day, at most one run every 20 hours (the data refreshes every 24 hours) | Apply via `applicationLink`, credit Himalayas with a link, do not pass jobs on to other boards, aggregators or Google Jobs, remove jobs once they expire. | yes | active |
| Greenhouse boards (`greenhouse`) | `https://boards-api.greenhouse.io/v1/boards/{board}/jobs` | none | 1 request per company per run, 200 a day | No published rate limit or third-party terms; the content belongs to each employer. Always link back to the posting's `absolute_url`. Companies: `GREENHOUSE_BOARDS`. | yes | active |
| Lever boards (`lever`) | `https://api.lever.co/v0/postings/{company}` | none | 1 request per company per run, 200 a day | Lever's README says published postings are public and may be read by third parties. Content belongs to each employer; always link back to `hostedUrl`. Companies: `LEVER_COMPANIES`. | yes | active |

### Notes

- **What "sent to the LLM" means.** The extraction step (`sanket.extraction`)
  sends a posting's text to Gemini unless its source is in
  `EXTRACTION_EXCLUDED_SOURCES`. On Gemini's free tier, Google may use API
  inputs to improve its models, which is why a source that reserves AI use
  must be excluded.
- **Request budgets** are counted per source per UTC day in the
  `source_request` table, retries included. A source over budget before its
  first request is reported as `skipped`.
- **Company lists** for the board sources (Greenhouse, Lever and, below,
  Ashby) are curated by the project owner through environment variables.

## Considered and skipped

No scraping. Each entry states why the source is not used and what would
change that.

| Source | Why it is skipped | Revisit when |
|---|---|---|
| NAV Norway (`pam-stilling-feed`) | Terms allow republishing and analysis, but access needs a token and written acceptance from NAV. Silent on AI processing and attribution. | NAV confirms in writing. |
| SmartRecruiters Posting API | The list call has no description, so every posting needs another request (N+1). No reuse terms found. | A curated company list needs it and terms are found. |
| Personio XML feeds, Teamtailor `jobs.rss` | Documented keyless per-company feeds, but no reuse terms found and low confidence. | A curated company list needs them and terms are found. |
| Arbeitnow | The API section only asks for a link back, but the general terms forbid commercial use, public display and mirroring. Ambiguous. | Written confirmation from Arbeitnow. |
| Dev Global Jobs | Free only for internal, research or non-commercial use; it re-lists other sites' jobs. | Never, for this use. |
| ReliefWeb (useful for Bangladesh and NGO jobs) | The API needs a pre-approved `appname`. The site terms say personal, non-commercial use only, and the content belongs to the contributing organisations. | OCHA gives permission (see below). |
| Working Nomads | An `exposed_jobs` endpoint exists, but the terms are silent on reuse and bar competing products. | Written confirmation. |
| Adzuna | Commercial analysis or resale of the data needs a written agreement. | An agreement is signed. |
| UN Careers RSS, UNjobs.org | Personal, non-commercial use only, and robots.txt disallows all bots. The UN feed has no descriptions. | Never, without permission. |
| Hacker News "Who is hiring?" | Y Combinator's terms bar data mining and scraping, and the posts are free text under the authors' copyright. | Never. |
| Recruitee | A token is required from 10 February 2027, and it is a per-company token. | Companies provide tokens. |
| Workable | No terms found. | Terms are found. |
| Reed, Careerjet, Jooble | Need a publisher key, and no readable terms permit storage or LLM use. Jooble bans bots. | Terms permitting our use are found. |
| The Muse, Findwork.dev | Terms or documentation unreadable or behind a login. | Terms become readable. |
| Remote.co, JustRemote, DevITjobs | No official feed or API. | An official feed appears. |
| Bdjobs | robots.txt on `www` disallows other bots. `api.bdjobs.com` has no published API or terms. | Written permission from Bdjobs. |
| Chakri.com, Skill.Jobs, jobs.gov.bd and other Bangladeshi aggregators | No official API or RSS found. | An official feed appears. |

**Bangladesh.** No permitted Bangladeshi source exists today. The practical
route is the boards of Bangladesh-based employers on Greenhouse, Lever or
Ashby (candidate slugs have not been verified), plus the permission requests
below.

## Permission requests the owner can send

These are the exact uses to ask for. Ask in writing and keep the reply; link it
here once received.

The use to request in each case: **store** the postings in our database,
**extract** structured fields from the text with a large language model,
compute **embeddings** for search, and **display** them in the Sanket product
with attribution and a link to the original listing. No re-publication as a
job board feed, no passing on to third parties, no model training.

1. **ReliefWeb (OCHA).** Ask for approval of an `appname` and permission for
   the use above. Mention that content belongs to the contributing
   organisations, so attribution names the employer and links to ReliefWeb.
2. **Arbeitnow.** Ask whether the use above is allowed under their API terms,
   given that the general terms forbid commercial use, public display and
   mirroring.
3. **Bdjobs.** Ask for written permission and, if they agree, for a documented
   feed or API. Until then nothing is fetched.
4. **NAV Norway** (if Norwegian postings become useful). Ask for the written
   acceptance their token process requires and a statement on AI processing
   and attribution.
