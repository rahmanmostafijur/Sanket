# 0001: Source admission policy

Status: accepted

## Context

Sanket stores job postings, runs them through an LLM, indexes them and shows
them to users. That is more than "reading" a feed, so a source's terms matter:
some forbid storage, public display, mirroring or AI use, and some are silent.
Until now each source was added case by case. The list will keep growing
(Phase 2 adds Ashby, JobTech Sweden and USAJOBS), and several candidates
turned out to have restrictive or unclear terms. The decision has to be made
once, written down and applied the same way every time.

## Options

1. **Take anything reachable.** Fast, but it means scraping and ignoring
   terms. It exposes the project to takedowns and bans, and it is not
   acceptable for a service meant to be shown publicly.
2. **Take any API or feed that exists, and rely on "it is public".** Public
   access is not permission to store, process with an LLM and redistribute.
3. **Admit a source only when its published terms (or the established nature
   of the endpoint) allow our use.** Slower, but every source has a stated
   basis, and a refusal or a missing permission is visible in one place.

## Decision

Option 3. A source is added only if it meets one of these two conditions.

1. **An official public API or RSS/JSON feed whose published terms allow
   storing, indexing, LLM processing and displaying postings with
   attribution.** The terms are read from the provider, not from a third
   party, and quoted or summarised in `docs/sources.md` and in the adapter
   docstring. If the licence name was not read, the docs say so.
2. **A documented public per-company job-board endpoint that employers
   publish for consumption** (Greenhouse, Lever, Ashby). There are no
   third-party terms for these. The content belongs to the employer, every
   posting links back to the employer's own posting, and we choose the
   company list ourselves. This is the precedent already used for Greenhouse
   and Lever; Ashby is admitted on the same basis.

A source is **skipped and documented** (never silently dropped) when any of
these holds:

- the terms are unclear, silent on storage, AI processing or display, or
  restrictive (personal or non-commercial use only, no mirroring, no data
  mining);
- an agreement, approval or token tied to a written acceptance is needed and
  has not been obtained;
- the only access is HTML pages. **No scraping, ever**, including sources
  whose robots.txt disallows bots.

Each admitted adapter also follows these rules:

- the adapter docstring states the terms that apply and the attribution duty;
- every posting keeps a link back to the original listing;
- request volume stays within the provider's limits, through the shared
  request budget (`max_requests_per_day`) and `min_interval`;
- a malformed item is skipped and counted, and never fails the whole run;
- credentials are optional settings. A source that needs a key and has none
  reports itself as `skipped` and makes no request;
- personal contact data in a payload (named people, emails, phone numbers) is
  removed before the payload is stored in `raw`;
- sources that reserve AI training or restrict model use are listed in
  `EXTRACTION_EXCLUDED_SOURCES` so their text never reaches the LLM.

Sources that were considered and skipped, with the evidence, are listed in
`docs/sources.md`. Skipped sources are revisited when written permission is
obtained or their terms change; `docs/sources.md` also lists the permission
requests the owner can send.

## Consequences

- Fewer sources at first, and no source of local (Bangladeshi) postings today,
  because none of them offers a permitted route. The practical route is
  Bangladesh-based employers' own boards on Greenhouse, Lever or Ashby and the
  permission requests listed in `docs/sources.md`.
- Adding a source requires a short terms review and a docs entry. This is a
  small, deliberate cost that keeps the data lawful and defensible.
- The policy is a statement of intent by the project owner, not legal advice.
  Terms change; the "last checked" dates in `docs/sources.md` say when each
  entry was read.
- Provider terms that are silent on attribution or AI processing are treated
  as not permitting them, until confirmed in writing.
