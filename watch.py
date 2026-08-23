"""
Weekly website watcher.

Scrapes a list of websites (via Firecrawl), asks an LLM (Claude, OpenAI,
or Gemini -- your choice) to summarize what's new compared to last run,
and emails you the report.

Required environment variables:
    FIRECRAWL_API_KEY   - from firecrawl.dev
    LLM_PROVIDER        - one of: "anthropic", "openai", "gemini"
    LLM_API_KEY         - API key for whichever provider you picked
    LLM_MODEL           - (optional) override the default model name
    EMAIL_FROM          - sender Gmail address
    EMAIL_TO            - recipient address (can be same as EMAIL_FROM)
    EMAIL_PASSWORD      - Gmail App Password (not your normal password)
"""

import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

FIRECRAWL_API_KEY = os.environ["FIRECRAWL_API_KEY"]
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL")  # optional override

EMAIL_FROM = os.environ["EMAIL_FROM"]
EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

STATE_FILE = "state.json"
SITES_FILE = "sites.json"

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.1-pro-preview",
}


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------

def scrape(url: str) -> str:
    resp = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"url": url, "formats": ["markdown"]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("data", {}).get("markdown", "") or ""


# --------------------------------------------------------------------------
# LLM providers (pick one via LLM_PROVIDER env var)
# --------------------------------------------------------------------------

CONTENT_CHARS_LIMIT = 120000


def _build_prompt(site_name: str, old_content: str, new_content: str) -> str:
    new_snippet = new_content[:CONTENT_CHARS_LIMIT]

    if not old_content:
        return (
            f'Here is the current content of the page "{site_name}" '
            "(this is the first time it is being checked, so there is "
            "nothing to compare it to yet):\n"
            f"{new_snippet}\n\n"
            "Extract the 3-5 most specific, concrete items actually present "
            "on this page right now — e.g. individual post titles, "
            "announcements, product launches, dated entries. Do NOT write a "
            "generic description of the company or its evergreen features/"
            "marketing copy. If the page is a blog or news listing, name the "
            "actual posts/topics found on it. Reply with ONLY the bullet "
            "points, one per line, each in the exact format "
            "'- Short title: one-sentence explanation of what it is and why "
            "it matters.' The title must be a few words only (e.g. the post "
            "name or feature name); the explanation must be a separate, "
            "genuinely informative sentence, not a repeat of the title. No "
            "intro sentence, no heading, no closing remark."
        )

    old_snippet = old_content[:CONTENT_CHARS_LIMIT]
    return (
        f'Here is the previous content of the page "{site_name}":\n'
        f"{old_snippet}\n\n"
        f"Here is the new content:\n"
        f"{new_snippet}\n\n"
        "Identify the 3-5 most specific, concrete things that are new or "
        "have changed — e.g. new post titles, new announcements, updated "
        "product details, added/removed entries. Do NOT restate generic, "
        "evergreen company/product description that was already there "
        "before. Reply with ONLY the bullet points, one per line, each in "
        "the exact format '- Short title: one-sentence explanation of what "
        "changed and why it matters.' The title must be a few words only "
        "(e.g. the post name or feature name); the explanation must be a "
        "separate, genuinely informative sentence, not a repeat of the "
        "title. No intro sentence, no heading, no closing remark. If "
        "nothing genuinely new was added, reply with a single bullet: "
        "'- No changes: nothing significant changed since the last check.'"
    )


def summarize_with_anthropic(prompt: str) -> str:
    model = LLM_MODEL or DEFAULT_MODELS["anthropic"]
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def summarize_with_openai(prompt: str) -> str:
    model = LLM_MODEL or DEFAULT_MODELS["openai"]
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def summarize_with_gemini(prompt: str) -> str:
    model = LLM_MODEL or DEFAULT_MODELS["gemini"]
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"Content-Type": "application/json"},
        params={"key": LLM_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


PROVIDERS = {
    "anthropic": summarize_with_anthropic,
    "openai": summarize_with_openai,
    "gemini": summarize_with_gemini,
}


def summarize_diff(site_name: str, old_content: str, new_content: str) -> str:
    prompt = _build_prompt(site_name, old_content, new_content)
    try:
        fn = PROVIDERS[LLM_PROVIDER]
    except KeyError:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. "
            f"Must be one of: {', '.join(PROVIDERS)}"
        )
    return fn(prompt)


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

def _bullets_to_html(summary: str) -> str:
    """Turn '- Title: explanation' lines into <li><strong>Title</strong>: explanation</li>."""
    lines = [l.strip(" -") for l in summary.strip().splitlines() if l.strip()]
    items = []
    for line in lines:
        title, sep, explanation = line.partition(":")
        if sep:
            items.append(f"<li><strong>{title.strip()}</strong>: {explanation.strip()}</li>")
        else:
            items.append(f"<li>{line}</li>")
    return f"<ul>{''.join(items)}</ul>"


def build_report_html(site_reports: list) -> str:
    """
    site_reports: list of dicts with keys: name, url, summary
    Produces one structured HTML email:
      1. General intro
      2. Short "how this works" note
      3. One section per site: bold title, bullets, link at the end
    """
    num_sites = len(site_reports)
    intro = (
        f"<p>Hi Mourad,</p>"
        f"<p>Here is your weekly watch report covering <b>{num_sites} site"
        f"{'s' if num_sites != 1 else ''}</b>. Below you'll find what's new "
        f"on each one since the last check.</p>"
    )

    architecture_note = (
        "<p style='color:#555;font-size:13px;'>"
        "<b>How this works:</b> each site is scraped weekly, compared to the "
        "previous version, and summarized by an AI model — fully automated, "
        "no manual checking needed."
        "</p><hr>"
    )

    sections = []
    for site in site_reports:
        bullets_html = _bullets_to_html(site["summary"])
        sections.append(
            f"<h3>{site['name']}</h3>"
            f"{bullets_html}"
            f"<p><a href='{site['url']}'>Visit {site['name']} →</a></p>"
            f"<hr>"
        )

    return intro + architecture_note + "".join(sections)


def send_email(html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = "Your weekly watch report"
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.send_message(msg)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    sites = load_json(SITES_FILE, [])
    state = load_json(STATE_FILE, {})

    if not sites:
        print("No sites configured in sites.json. Nothing to do.")
        return

    site_reports = []

    for site in sites:
        name, url = site["name"], site["url"]
        print(f"Scraping {name} ({url})...")
        try:
            new_content = scrape(url)
        except Exception as exc:
            print(f"  -> scrape failed: {exc}")
            site_reports.append(
                {"name": name, "url": url, "summary": f"- Scraping error: {exc}"}
            )
            continue

        old_content = state.get(url, "")

        try:
            summary = summarize_diff(name, old_content, new_content)
        except Exception as exc:
            print(f"  -> summarization failed: {exc}")
            summary = f"- Summary failed: {exc}"

        site_reports.append({"name": name, "url": url, "summary": summary})
        state[url] = new_content

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    html_body = build_report_html(site_reports)
    print("\n----- REPORT (HTML) -----\n")
    print(html_body)

    send_email(html_body)
    print("\nEmail sent.")


if __name__ == "__main__":
    main()
