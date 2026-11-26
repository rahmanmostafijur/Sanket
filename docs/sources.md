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
| Ashby boards (`ashby`) | `https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | none | 1 request per company per run, 200 a day. One response holds the whole board (several MB for a large one); no per-job requests. | Ashby's documented public posting API, admitted on the same basis as Greenhouse and Lever (ADR 0001). No third-party terms; the content belongs to each employer. Always link back to `jobUrl`. Unlisted jobs are dropped. Companies: `ASHBY_BOARDS`. | yes | active once `ASHBY_BOARDS` is set; with none configured it fetches nothing |
| JobTech Sweden (`jobtech_se`) | `https://jobsearch.api.jobtechdev.se/search` (JobSearch API) | none | Newest first, at most `JOBTECH_MAX_PAGES` pages of 100 per run (default 5, API maximum 20), one request a second, at most one run an hour, `JOBTECH_MAX_PAGES` x 8 requests a day. | Official open data from the Swedish Public Employment Service (Arbetsformedlingen), published as "free to use and share regardless of purpose" (data.jobtechdev.se; the open data page on arbetsformedlingen.se). **The name of the licence was not read and no attribution rule was found**; each posting still links back to its Platsbanken page and the source is named. Named contacts, emails and phone numbers are removed from `raw` before storage. | yes | active. Not limited to tech jobs: `JOBTECH_QUERY` narrows it. |
| USAJOBS (`usajobs`) | `https://data.usajobs.gov/api/Search` (`DatePosted=2`, `ResultsPerPage=500`, `WhoMayApply=public`, `Fields=Full`) | free API key (`USAJOBS_API_KEY`) and the email it was registered with (`USAJOBS_USER_AGENT_EMAIL`, sent as the User-Agent) | At most 5 pages of 500 per run, one request a second, at most one run an hour, 40 requests a day. | Terms of Service (developer.usajobs.gov): Public Data "may be copied, stored, reformatted, adapted, analyzed, published, redistributed, and used for lawful commercial or noncommercial purposes. Prior OPM approval is not required." Identifying USAJOBS as the source is encouraged and the retrieval date should be included (the posting's first and last seen times record it). Do not claim OPM endorsement. | yes | **skipped** without the key and email (no request is made); active when both are set |

### Notes

- **What "sent to the LLM" means.** The extraction step (`sanket.extraction`)
  sends a posting's text to Gemini unless its source is in
  `EXTRACTION_EXCLUDED_SOURCES`. On Gemini's free tier, Google may use API
  inputs to improve its models, which is why a source that reserves AI use
  must be excluded.
- **Request budgets** are counted per source per UTC day in the
  `source_request` table, retries included. A source over budget before its
  first request is reported as `skipped`.
- **Company lists** for the board sources (Greenhouse, Lever and Ashby) are
  curated by the project owner through environment variables.
- **"Skipped" status.** A source reports `skipped` when it is not configured
  (USAJOBS without credentials), ran less than its minimum interval ago, or
  has used up its daily request budget. It is not a failure.
- **USAJOBS is documentation-derived.** No API key was available when it was
  built, so its test fixture is hand-written from the response shape in the
  USAJOBS documentation, not a recording. Which fields the live API fills in,
  and their exact format (for example whether `MajorDuties` is a list or a
  string, or what salary strings look like), is unverified. Check the first
  live run's output before relying on it.
- **JobTech.** JobSearch was chosen because it is simple and verified. JobStream,
  the bulk change feed from the same provider, is the alternative if a full
  copy of the Swedish ads is ever needed; it is not built. The API's
  timestamps have no offset, so they are read as Swedish time
  (Europe/Stockholm) before being stored in UTC.
- **Ashby.** The payload has no company name, so the board name stands in for
  the company, as for Lever. The employer's compensation summary is stored as
  the salary text unless the employer chose not to display it.

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
| Careerjet (locale `en_BD`) | Terms read on 27 Nov 2026 (visible without an account; the key comes from a publisher account). They say nothing on storing results, attribution or numeric rate limits, and `en_BD` is not documented as supported (an unsupported locale returns HTTP 400). They bar using the API to "extract or collect job listings in bulk for purposes unrelated to displaying them to jobseekers" and to "build or maintain an independent job database, search index, or competing job search service". Every call must carry the real end user's `user_ip` and `user_agent`, the calling server's fixed IP must be declared first, and serverless or dynamic-IP hosting is not supported. That suits live per-user searches, not scheduled ingestion into our database. | Careerjet confirms in writing that storing and indexing results is allowed, and `en_BD` works. |
| Reed, Jooble | Need a publisher key, and no readable terms permit storage or LLM use. Jooble bans bots. | Terms permitting our use are found. |
| The Muse, Findwork.dev | Terms or documentation unreadable or behind a login. | Terms become readable. |
| Remote.co, JustRemote, DevITjobs | No official feed or API. | An official feed appears. |
| Bdjobs | robots.txt on `www` disallows other bots. `api.bdjobs.com` has no published API or terms. | Written permission from Bdjobs. |
| Chakri.com, Skill.Jobs, jobs.gov.bd and other Bangladeshi aggregators | No official API or RSS found. | An official feed appears. |
| Talenthic (Bangladeshi aggregator, `talenthic.info/api/public/v1`) | Needs an API key from an account, and whether the key is free is not stated. Its terms say nothing on storing results, bulk or scheduled pulls, or embeddings and LLM extraction (they bar training a general-purpose model without a written agreement, and scraping the site). They require attribution and honouring employer takedowns. It re-lists other employers' postings and offers competing job discovery. Silence on storage means skipped under ADR 0001. | Talenthic confirms in writing: storage, LLM extraction, embeddings, scheduled pulls, the key terms. |
| ReliefWeb API (`country=Bangladesh`) | Rechecked 27 Nov 2026: every call needs a pre-approved `appname`, the docs defer to terms that limit reuse, and the live terms page could not be read (403). An archived copy allowed personal, non-commercial use only. | OCHA approves an `appname` and permits our use. |
| Ain o Salish Kendra vacancy RSS | The feed sits behind a JavaScript bot challenge, so neither the feed nor any terms could be read, and a challenge must not be bypassed. One NGO. | Terms and an open feed are published. |
| Bikroy jobs, CSE/EEE Jobs BD, BRAC Careers, Devex, Impactpool | HTML pages only (or blocked to automated reads), no feed or API, no reuse terms found. | An official feed with terms appears. |
| data.gov.bd, BCC, a2i and the per-agency government portals | No jobs dataset or unified API found; recruitment runs on per-agency HTML portals. | A jobs dataset with an open licence is published. |
| Techmap Bangladesh data | Paid product (AWS Data Exchange). | Never, without a paid plan the owner approves. |
| Careerjet (`en_BD`) | Terms read on 27 Nov 2026: they bar bulk collection and an independent job database, and need the end user's IP and agent on every call. | Careerjet confirms storage in writing. |

**Bangladesh.** No Bangladeshi aggregator, government portal or open-data
portal offers an official feed with reusable terms, so none is added. What
does qualify is ADR 0001 condition 2, per-company boards. On 27 Nov 2026
about 330 candidate slugs were probed on Greenhouse, Lever and Ashby. Every
Bangladesh-headquartered company tried (Pathao, bKash, Brain Station 23,
Selise, Cefalo, Therap, ShopUp, Chaldal, Tiger IT, BJIT, Enosis, Nagad, SSL
Wireless, Pickaboo, Daraz and others) returned 404 on all three platforms, and
about 100 global employers that do have boards list no Bangladesh job. Three
boards with Bangladesh postings were verified live and added to the example
company lists in `.env.example` (production lists are the repository
variables `GREENHOUSE_BOARDS` and `LEVER_COMPANIES`, which the owner sets):

| Board | Platform | Bangladesh jobs on 27 Nov 2026 | Note |
|---|---|---|---|
| `wppproduction` (WPP) | Greenhouse | 4 of 169, Dhaka | Multinational agency; the adapter takes the whole board, so most postings are outside Bangladesh. |
| `applytopopulate` (Populate) | Greenhouse | 3 of 6, one Dhaka and two remote from Bangladesh | US company; its postings were last updated in February 2026 and may be stale. |
| `fieldnation` (Field Nation) | Lever | 10 of 16, Dhaka | US company with a development and operations centre in Dhaka. |

Greenhouse and Lever publish no reuse terms for these endpoints, and neither
platform's documentation addresses AI processing. The hosted Lever pages
(`jobs.lever.co`) carry a content signal that reserves AI training; it is not
on the API host, and nothing here trains a model, but it is a reason to keep
`lever` in mind if extraction exclusions are ever tightened. Ashby has no
board with a Bangladesh job. Volume is small (17 Bangladesh postings), so more
local coverage depends on the permission requests below or on finding more
Dhaka-office employers (test each slug against the public endpoint first).

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
5. **Talenthic** (Bangladeshi postings). Ask for the use above plus scheduled
   pulls, whether an API key is free, the hourly rate limit, and how employer
   takedown requests reach us. Their terms ask for attribution of the employer
   and bar training a general-purpose model, so confirm that embeddings and
   LLM extraction fall inside the use they allow.
