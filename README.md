# Weekly Website Watch

Scrapes a list of websites every week, asks an LLM to summarize what's
new since last time, and emails you the report. Runs for free on
GitHub Actions.

## Environment variables needed

- `FIRECRAWL_API_KEY` — from firecrawl.dev
- `LLM_PROVIDER` — `anthropic`, `openai`, or `gemini`
- `LLM_API_KEY` — API key for whichever provider you picked
- `LLM_MODEL` — (optional) override the default model
- `EMAIL_FROM` — sender Gmail address
- `EMAIL_TO` — recipient address
- `EMAIL_PASSWORD` — Gmail App Password
