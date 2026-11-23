# Sanket frontend

The web app for Sanket: job search, profile matching and the live match feed.
React 19, TypeScript (strict), Vite, Tailwind CSS v4, Motion, Radix primitives, TanStack Query, React Router and Zustand.

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
```

The app calls the API at `/api`. In development Vite proxies `/api/*` to `http://127.0.0.1:8000`
(override with `API_PROXY_TARGET` in `frontend/.env.local`). Start the API with `python -m sanket.api`.

Credentials: the API accepts a bearer API key or JWT. Paste one in **API & Integrations**. It is
kept for the current tab, or on the device if you tick "Remember on this device". With
`AUTH_DEV_BYPASS=true` (never in production) the API admits calls without one.

If the API is not reachable, the app says so and offers **demo data**: fictional listings
generated in the browser. Demo mode is labelled on every screen, and its simulated feed shows as
"Demo stream", never as "Live".

## Checks

```bash
npm run lint
npm run typecheck
npm test             # Vitest: stream client, API client, filters, formatting, match explanations
npm run build        # dist/
```

## Production

The API sends no CORS headers, so serve `dist/` and the API from the same origin and route
`/api/` to the API (and `try_files $uri /index.html` for client-side routes). For a different
path, build with `VITE_API_BASE_URL=/your/path`. Turn off proxy buffering for
`/api/profiles/*/matches/stream`; the API already sends `X-Accel-Buffering: no`.

## How it maps to the API

| Screen | Endpoints |
| --- | --- |
| Overview, Live Matches | `GET /profiles`, `GET /profiles/{id}/matches`, `POST /auth/stream-token`, `GET /profiles/{id}/matches/stream` (SSE) |
| Discover Jobs | `GET /search` (work mode, seniority, employment type and source filters go to the API) |
| My Profile | `POST`, `PUT`, `DELETE /profiles/{id}` |
| API & Integrations | `GET /healthz` |

What the API does not provide, and how the app handles it:

- **No job lookup by id.** Job details come from jobs already loaded (search results, matches,
  saved jobs; cached per tab) and link to the original listing for the full description.
- **Match scores** exist only for jobs in your profile's matches. Other jobs show no score.
- **Salary filter and sorting** run in the browser on the results loaded so far, and only for
  salaries stated in USD.
- **Saved jobs** are stored in this browser.
- **API keys** are issued by the server operator (`AUTH_API_KEYS`). There are no endpoints to
  create, revoke or meter them.
- **Salary Insights** is a placeholder until the API has salary analytics.

The live feed (`src/features/live/streamClient.ts`) mints a fresh stream token on every
(re)connect, resumes with `last_event_id`, backs off exponentially, ignores repeated event ids and
reports `connecting`, `open`, `reconnecting`, `offline` and `failed`.

## Layout

```
src/
  api/          types mirroring the backend schemas, fetch client, endpoints
  data/         DataSource interface: the API, or the labelled demo data set
  features/     live feed client, filter model, match explanations
  hooks/        TanStack Query hooks and small shared hooks
  stores/       Zustand: session, saved jobs, preferences, live feed, toasts
  components/   ui primitives, layout shell, job and match components
  pages/        one folder per route, lazy loaded
```
