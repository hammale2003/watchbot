# Weekly Website Watch

Scrapes a list of websites every week (via Firecrawl), asks an LLM
(Claude, GPT, or Gemini — your choice) to summarize what changed since
last time, and emails you the report. Runs for free on GitHub Actions,
no server needed.

## Files

- `watch.py` — the script that does everything
- `test_watch.py` — automated tests (mocked APIs, no real keys needed)
- `sites.json` — list of sites you want to watch
- `state.json` — auto-updated, stores last scraped content per site
- `.github/workflows/weekly_watch.yml` — the schedule (every Monday 8am UTC)
- `.env.example` — template of required environment variables

## Setup

1. Push this project to a GitHub repo.
2. Edit `sites.json` with the sites you want to track.
3. Go to **Settings → Secrets and variables → Actions** in your repo and
   add these secrets (values from `.env.example`):
   - `FIRECRAWL_API_KEY`
   - `LLM_PROVIDER` (`anthropic`, `openai`, or `gemini`)
   - `LLM_API_KEY`
   - `LLM_MODEL` (optional)
   - `EMAIL_FROM`
   - `EMAIL_TO`
   - `EMAIL_PASSWORD` (Gmail App Password, not your normal password)
4. Done. It runs automatically every Monday. You can also trigger it
   manually any time from the **Actions** tab → "Weekly Watch" → "Run workflow".

## Running tests locally

```bash
pip install -r requirements.txt
python test_watch.py
```

This runs the full pipeline against mocked Firecrawl/LLM/email calls —
no API keys or network access required — to confirm the logic works
before you plug in real credentials.

## Running for real, locally

```bash
pip install -r requirements.txt
export FIRECRAWL_API_KEY=...
export LLM_PROVIDER=anthropic
export LLM_API_KEY=...
export EMAIL_FROM=...
export EMAIL_TO=...
export EMAIL_PASSWORD=...
python watch.py
```
