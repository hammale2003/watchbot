"""
Functional test for watch.py using mocked HTTP calls (no real network access,
no real API keys needed). Verifies the full flow: scrape -> diff -> summarize
-> state persisted -> email composed, for all 3 LLM providers.
"""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("EMAIL_FROM", "me@example.com")
os.environ.setdefault("EMAIL_TO", "me@example.com")
os.environ.setdefault("EMAIL_PASSWORD", "test-password")

sys.path.insert(0, os.path.dirname(__file__))


def fake_post(url, headers=None, json=None, params=None, timeout=None, **kwargs):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()

    if "firecrawl.dev" in url:
        resp.json.return_value = {
            "data": {"markdown": f"# Fake page content for {json['url']}\nSome new stuff happened."}
        }
    elif "anthropic.com" in url:
        resp.json.return_value = {"content": [{"text": "- Claude says: new stuff happened."}]}
    elif "openai.com" in url:
        resp.json.return_value = {
            "choices": [{"message": {"content": "- GPT says: new stuff happened."}}]
        }
    elif "generativelanguage.googleapis.com" in url:
        resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "- Gemini says: new stuff happened."}]}}]
        }
    else:
        raise AssertionError(f"Unexpected URL called: {url}")
    return resp


class FakeSMTP:
    sent_messages = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pwd):
        assert pwd == "test-password"

    def send_message(self, msg):
        FakeSMTP.sent_messages.append(msg)


class TestWatchScript(unittest.TestCase):
    def setUp(self):
        # fresh temp working dir per test
        self.tmpdir = f"/tmp/watch_test_{id(self)}"
        os.makedirs(self.tmpdir, exist_ok=True)
        os.chdir(self.tmpdir)
        with open("sites.json", "w") as f:
            json.dump([{"name": "Test Site", "url": "https://example.com"}], f)
        with open("state.json", "w") as f:
            json.dump({}, f)
        FakeSMTP.sent_messages = []

    def _run_with_provider(self, provider):
        os.environ["LLM_PROVIDER"] = provider
        import importlib
        import watch
        importlib.reload(watch)

        with mock.patch("requests.post", side_effect=fake_post), \
             mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            watch.main()

        # state.json should now contain the scraped content
        with open("state.json") as f:
            state = json.load(f)
        self.assertIn("https://example.com", state)
        self.assertIn("Fake page content", state["https://example.com"])

        # an email should have been "sent"
        self.assertEqual(len(FakeSMTP.sent_messages), 1)
        part = FakeSMTP.sent_messages[0].get_payload()[0]
        body = part.get_payload(decode=True).decode("utf-8")
        self.assertIn("<h3>Test Site</h3>", body)
        self.assertIn("<ul><li>", body)
        self.assertIn("Visit Test Site", body)
        self.assertIn("href='https://example.com'", body)
        return body

    def test_anthropic_provider(self):
        body = self._run_with_provider("anthropic")
        self.assertIn("Claude says", body)

    def test_openai_provider(self):
        body = self._run_with_provider("openai")
        self.assertIn("GPT says", body)

    def test_gemini_provider(self):
        body = self._run_with_provider("gemini")
        self.assertIn("Gemini says", body)

    def test_second_run_uses_previous_state_as_diff_base(self):
        os.environ["LLM_PROVIDER"] = "anthropic"
        import importlib
        import watch
        importlib.reload(watch)

        captured_prompts = []

        def capturing_post(url, headers=None, json=None, params=None, timeout=None, **kwargs):
            if "anthropic.com" in url:
                captured_prompts.append(json["messages"][0]["content"])
            return fake_post(url, headers, json, params, timeout, **kwargs)

        with mock.patch("requests.post", side_effect=capturing_post), \
             mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            watch.main()  # first run: no previous data
            watch.main()  # second run: should diff against state from run 1

        self.assertIn("no previous data", captured_prompts[0])
        self.assertIn("Fake page content", captured_prompts[1])  # old content now present


if __name__ == "__main__":
    unittest.main(verbosity=2)
