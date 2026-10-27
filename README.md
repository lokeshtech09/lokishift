# LokiShift

Keep several versions of your resume per job title, paste a job description,
and LokiShift picks the best version, shows the match score, and tailors it in
the background — no questions asked. You get a notification when the tailored
`.docx` is ready to download and mail to the vendor.

## How it works

```
Profile (one per job title: "Python Developer", "Data Engineer", …)
  └── Resumes (N .docx versions, formatting kept)

New Resume Task (JD + vendor details)
  1. Matching   – every resume in the profile is scored against the JD (AI + keyword score); best one wins
  2. Tailoring  – one click (or automatic): summary, skills and bullets rewritten toward the JD,
                  new bullets added for JD responsibilities the resume doesn't cover
  3. Finished   – download the tailored .docx, "Mail Vendor" opens a pre-filled email draft

Reports – trends over time, top vendors, positions (similar titles grouped), locations,
          profiles and domains, average match and tailoring gain, plain-English insights
```

Both steps run in a background worker, so you can create several tasks and keep working.
Contact details, client/company names, job titles, dates and section headings are
hard-locked: the AI can't change them. Lines built from the JD rather than your resume are
listed on the task page under **"Added from the job description"** so you know what to prepare
for in interviews.

## Quick start

You need **[Node.js 22+](https://nodejs.org)** (the LTS installer is fine) and **git**.
Python is handled for you by `uv`, which `setup.sh` installs if it's missing.

```bash
git clone https://github.com/<your-username>/LokiShift.git
cd LokiShift
./setup.sh     # one time: installs everything (a few minutes)
./start.sh     # every time: opens http://localhost:3000 — Ctrl+C to stop
```

**Windows:** use [Docker Desktop](https://www.docker.com/products/docker-desktop/) instead
(see [Docker](#docker) below), or run the two scripts inside WSL.

### First run: 3 steps

1. **Settings → Add connection.** Pick a provider (OpenAI, Gemini, Anthropic, Groq, OpenRouter,
   DeepSeek, Azure, a local Ollama…), choose a model, paste your API key and save. The plug icon tests it.
2. **Profiles → New Profile** for each job title you apply for (e.g. "Data Engineer"), then
   upload your `.docx` resume versions into it.
3. **New Resume Task** (sidebar). Paste the job description and vendor details. LokiShift
   picks the best resume, shows the match score, and tailors it in the background. The
   Dashboard notifies you when the tailored `.docx` is ready.

### Your data stays on your computer

Everything you add (profiles, resumes, tasks, encrypted keys) lives in `apps/backend/data/`,
which git ignores, so it is never committed or pushed. To back up, copy that folder.
To start fresh, stop the app and delete it.

### More about AI connections

You can add several connections (different providers, or several keys for one provider),
star one as the **default**, and mark others as **backups**: if the default fails (no credit,
quota used up, outage, key rejected), the task automatically retries on the backups, top to
bottom. A single task can also pick its own connection on the New Resume Task form.

### Manual setup (developers)

```bash
cd apps/backend  && uv sync && uv run uvicorn app.main:app --reload --port 8000   # API docs: /docs
cd apps/frontend && npm install && npm run dev                                    # http://localhost:3000
```

### How your API key is protected

- Entered **only** on the Settings page (one key per connection); environment variables and
  `.env` are never read.
- Stored **encrypted** in the database in `apps/backend/data` (owner-only file permissions).
- **Never sent back**: the API only says whether a key is saved, never any characters of it.
- **Scrubbed from logs**: key-like text in any log line or error trace is replaced with `<redacted>`.
- **This computer only**: the backend and frontend listen on `127.0.0.1`, so other devices on
  your network can't use the app (or your key). Docker publishes on `127.0.0.1` too.

### Docker

```bash
docker compose up --build    # http://localhost:3000, data kept in the resume-data volume
```

## Optional server settings

No `.env` file is needed: everything has a sensible default. To change one, set it as an
environment variable when starting the backend (e.g. `WORKER_CONCURRENCY=2 uv run uvicorn …`).
The AI provider, model and key are never set this way — only on the Settings page.

| Variable | Default | Meaning |
|---|---|---|
| `WORKER_CONCURRENCY` | `1` | Background jobs running at once |
| `JOB_TIMEOUT_SECONDS` | `900` | Max time for one matching/tailoring job |
| `JOB_RATE_LIMIT_RETRIES` | `3` | Waits on provider rate limits before a job fails |

## Project layout

```
apps/backend    FastAPI + SQLite: profiles, resumes, tasks, background worker, LLM tailoring
apps/frontend   Next.js 16 + Tailwind: Dashboard, Tasks, Profiles, Reports, Settings
docker/         Single-container start script
```

Tests: `cd apps/backend && uv sync --extra dev && uv run pytest` (the LLM is stubbed).
Frontend checks: `npm run typecheck && npm run lint && npm run build`.

## Credits

Built on [Resume Matcher](https://github.com/srbhr/Resume-Matcher) by Saurabh Rai and
contributors, licensed under Apache 2.0 (see `LICENSE`).
