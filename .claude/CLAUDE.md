# CLAUDE.md - LokiShift

LokiShift matches a candidate's resume versions to a job description and tailors the best one
in the background. Single local user (no auth yet).

| Layer | Stack |
|---|---|
| Backend (`apps/backend`) | FastAPI, Python 3.13, SQLAlchemy 2 async + SQLite, LiteLLM, python-docx |
| Frontend (`apps/frontend`) | Next.js 16 (app router), React 19, Tailwind v4, lucide-react |

## Domain

Profile (job title) → ProfileResume (N .docx versions) · Task (JD + vendor) with status
`matching → matched → tailoring → finished | failed`.

## Where things live

- Backend details: `apps/backend/CLAUDE.md`
- Frontend: `app/(app)/{dashboard,tasks,tasks/new,tasks/[id],profiles,profiles/[id],reports,settings}`,
  shared pieces in `components/` (`activity-provider.tsx` polls `/api/v1/dashboard` and shows
  toasts), API client + types in `lib/api.ts`.
- The frontend talks to the backend through the Next.js `/api` rewrite (`next.config.ts`).

## Rules

- Tailoring writes into the user's own DOCX; never regenerate documents from scratch.
- Anything the AI must never change goes in `is_protected()` (backend), not only in the prompt.
- Run before finishing: `uv run pytest` (backend), `npm run typecheck && npm run lint && npm run build` (frontend).
