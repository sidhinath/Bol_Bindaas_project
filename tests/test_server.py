"""Backend unit and integration tests for BolBindaas.

No API key and no external network access are needed: Gemini is either mocked
at the urllib boundary or replaced by a local HTTP server.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

EXPECTED_SYSTEM_PROMPT = (
    "Rewrite Hinglish (Hindi written in Roman script mixed with English) "
    "into clear, natural, grammatically correct English. Preserve every "
    "exact action, subject, intent, emotion, and tone without altering or "
    "guessing the meaning (e.g. distinguish accurately between "
    "\"pehnunga\" = \"to wear\" vs \"dhona\" = \"to wash\"). Output ONLY "
    "the English translation — no explanations, quotes, or extra commentary."
)

ENV_KEYS = (
    "AI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "AI_BASE_URL",
    "AI_MODEL",
    "AI_FALLBACK_MODEL",
    "AI_TIMEOUT_SECONDS",
    "AI_MAX_ATTEMPTS",
    "AI_DEBUG",
    "AI_ALLOW_LEGACY_MODEL",
    "AI_PROVIDER",
    "PROVIDER",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_MODEL",
    "GROQ_MODEL",
    "OPENROUTER_MODEL",
    "OPENAI_BASE_URL",
    "GROQ_BASE_URL",
    "OPENROUTER_BASE_URL",
)


def clear_ai_env():
    for key in ENV_KEYS:
        os.environ.pop(key, None)


class FakeResponse:
    """Minimal context-manager response for urllib.request.urlopen."""

    def __init__(self, payload):
        self.status = 200
        if isinstance(payload, bytes):
            self.body = payload
        else:
            self.body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class MockGeminiHandler(BaseHTTPRequestHandler):
    """Local stand-in for the Gemini generateContent endpoint."""

    status = 200
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "Today I am feeling a little low."}]}}
        ]
    }
    responses = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )

        if type(self).responses:
            status, payload = type(self).responses.pop(0)
        else:
            status, payload = type(self).status, type(self).payload

        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class QuietAppHandler(server.AppHandler):
    def log_message(self, *args):
        pass


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.saved_config = copy.deepcopy(server.CONFIG)
        self.saved_debug = server.DEBUG
        self.saved_timeout = server.GEMINI_TIMEOUT_SECONDS
        self.saved_attempts = server.MAX_ATTEMPTS

    def tearDown(self):
        server.CONFIG.clear()
        server.CONFIG.update(self.saved_config)
        server.DEBUG = self.saved_debug
        server.GEMINI_TIMEOUT_SECONDS = self.saved_timeout
        server.MAX_ATTEMPTS = self.saved_attempts

    def test_system_prompt_matches_the_required_text_verbatim(self):
        self.assertEqual(server.SYSTEM_PROMPT, EXPECTED_SYSTEM_PROMPT)

    def test_defaults_are_used_when_no_environment_is_set(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            clear_ai_env()
            with contextlib.redirect_stdout(io.StringIO()):
                server.configure()

            self.assertEqual(server.CONFIG["key"], "")
            self.assertEqual(
                server.CONFIG["base_url"],
                "https://generativelanguage.googleapis.com/v1beta",
            )
            self.assertEqual(server.CONFIG["model"], "gemini-3.5-flash-lite")
            self.assertEqual(server.CONFIG["fallback_model"], "gemini-3.1-flash-lite")
            self.assertEqual(server.CONFIG["provider"], "auto")
            self.assertEqual(
                server.CONFIG["keys"],
                {"gemini": "", "openai": "", "groq": "", "openrouter": ""},
            )
            self.assertEqual(server.GEMINI_TIMEOUT_SECONDS, 30)
            self.assertEqual(server.MAX_ATTEMPTS, 3)
            self.assertFalse(server.DEBUG)

    def test_retry_settings_can_be_overridden_and_clamped(self):
        with patch.dict(
            os.environ,
            {"AI_TIMEOUT_SECONDS": "500", "AI_MAX_ATTEMPTS": "99"},
        ), patch.object(server, "load_env", lambda: None):
            server.configure()

            self.assertEqual(server.GEMINI_TIMEOUT_SECONDS, 120)
            self.assertEqual(server.MAX_ATTEMPTS, 5)

    def test_fallback_model_can_be_customized_or_disabled(self):
        with patch.dict(os.environ, {"AI_FALLBACK_MODEL": "gemini-custom-lite"}), patch.object(
            server, "load_env", lambda: None
        ):
            server.configure()
            self.assertEqual(server.CONFIG["fallback_model"], "gemini-custom-lite")

        with patch.dict(os.environ, {"AI_FALLBACK_MODEL": "gemini-3.5-flash-lite"}), patch.object(
            server, "load_env", lambda: None
        ):
            server.configure()
            self.assertEqual(server.CONFIG["fallback_model"], "")

    def test_debug_mode_can_be_disabled(self):
        with patch.dict(os.environ, {"AI_DEBUG": "0"}), patch.object(
            server, "load_env", lambda: None
        ):
            server.configure()
            self.assertFalse(server.DEBUG)

    def test_ai_api_key_has_priority_over_other_key_names(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            clear_ai_env()
            os.environ["AI_API_KEY"] = "primary-key"
            os.environ["GEMINI_API_KEY"] = "gemini-key"
            os.environ["GOOGLE_API_KEY"] = "google-key"
            server.configure()

            self.assertEqual(server.CONFIG["key"], "primary-key")

    def test_gemini_and_google_key_fallbacks_are_supported(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            for variable in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                with self.subTest(variable=variable):
                    clear_ai_env()
                    os.environ[variable] = "fallback-key"
                    server.configure()
                    self.assertEqual(server.CONFIG["key"], "fallback-key")

    def test_all_provider_keys_and_selection_are_loaded(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            clear_ai_env()
            os.environ.update(
                {
                    "GEMINI_API_KEY": "gemini-key",
                    "OPENAI_API_KEY": "openai-key",
                    "GROQ_API_KEY": "groq-key",
                    "OPENROUTER_API_KEY": "openrouter-key",
                    "AI_PROVIDER": "openai",
                }
            )
            with contextlib.redirect_stdout(io.StringIO()):
                server.configure()

            self.assertEqual(server.CONFIG["provider"], "openai")
            self.assertEqual(server.provider_key("gemini"), "gemini-key")
            self.assertEqual(server.provider_key("openai"), "openai-key")
            self.assertEqual(server.provider_key("groq"), "groq-key")
            self.assertEqual(server.provider_key("openrouter"), "openrouter-key")
            self.assertEqual(
                server.configured_providers(),
                ["groq", "gemini", "openai", "openrouter"],
            )

    def test_unknown_provider_selection_falls_back_to_auto(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "somewhere"}), patch.object(
            server, "load_env", lambda: None
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                server.configure()

            self.assertEqual(server.CONFIG["provider"], "auto")
            self.assertIn("Ignoring unknown AI_PROVIDER", output.getvalue())

    def test_chat_provider_settings_can_be_overridden(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": "gpt-4o",
                "OPENAI_BASE_URL": "https://openai.example/v1",
                "GROQ_MODEL": "custom-groq-model",
            },
        ), patch.object(server, "load_env", lambda: None):
            with contextlib.redirect_stdout(io.StringIO()):
                server.configure()

            self.assertEqual(server.provider_setting("openai", "model"), "gpt-4o")
            self.assertEqual(
                server.provider_setting("openai", "base_url"),
                "https://openai.example/v1",
            )
            self.assertEqual(server.provider_setting("groq", "model"), "custom-groq-model")
            self.assertEqual(
                server.provider_setting("openrouter", "base_url"),
                "https://openrouter.ai/api/v1",
            )

    def test_stale_openai_base_url_and_model_are_ignored(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            clear_ai_env()
            os.environ["AI_API_KEY"] = "test-key"
            os.environ["AI_BASE_URL"] = "https://api.openai.com/v1"
            os.environ["AI_MODEL"] = "gpt-4o-mini"

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                server.configure()

            self.assertEqual(
                server.CONFIG["base_url"],
                "https://generativelanguage.googleapis.com/v1beta",
            )
            self.assertEqual(server.CONFIG["model"], "gemini-3.5-flash-lite")
            self.assertIn("Ignoring old OpenAI", output.getvalue())

    def test_slow_legacy_model_is_automatically_replaced(self):
        with patch.dict(os.environ, {"AI_MODEL": "gemini-3.8-flash"}), patch.object(
            server, "load_env", lambda: None
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                server.configure()

            self.assertEqual(server.CONFIG["model"], "gemini-3.5-flash-lite")
            self.assertIn("Switching slow legacy", output.getvalue())

    def test_legacy_model_can_be_kept_with_an_explicit_opt_in(self):
        with patch.dict(
            os.environ,
            {"AI_MODEL": "gemini-3.8-flash", "AI_ALLOW_LEGACY_MODEL": "1"},
        ), patch.object(server, "load_env", lambda: None):
            with contextlib.redirect_stdout(io.StringIO()):
                server.configure()

            self.assertEqual(server.CONFIG["model"], "gemini-3.8-flash")

    def test_custom_gemini_settings_are_used(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(
            server, "load_env", lambda: None
        ):
            clear_ai_env()
            os.environ["AI_API_KEY"] = "test-key"
            os.environ["AI_BASE_URL"] = "https://gemini.example/v1beta/"
            os.environ["AI_MODEL"] = "gemini-custom"
            server.configure()

            self.assertEqual(server.CONFIG["base_url"], "https://gemini.example/v1beta/")
            self.assertEqual(server.CONFIG["model"], "gemini-custom")

    def test_load_env_does_not_override_real_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                'AI_API_KEY=from-file\nAI_MODEL="gemini-from-file"\n', encoding="utf-8"
            )

            with patch.dict(os.environ, {}, clear=False), patch.object(
                server, "ROOT", Path(tmp)
            ):
                clear_ai_env()
                os.environ["AI_API_KEY"] = "from-env"

                server.load_env()

                self.assertEqual(os.environ["AI_API_KEY"], "from-env")
                self.assertEqual(os.environ["AI_MODEL"], "gemini-from-file")


class CallAiTests(unittest.TestCase):
    def setUp(self):
        self.saved_config = copy.deepcopy(server.CONFIG)
        self.saved_timeout = server.GEMINI_TIMEOUT_SECONDS
        self.saved_attempts = server.MAX_ATTEMPTS
        self.saved_debug = server.DEBUG
        server.CONFIG.update(
            {
                "key": "test-gemini-key",
                "base_url": "https://gemini.example/v1beta",
                "model": "gemini-3.5-flash-lite",
                "fallback_model": "gemini-3.1-flash-lite",
                "provider": "auto",
                "keys": {
                    "gemini": "test-gemini-key",
                    "openai": "",
                    "groq": "",
                    "openrouter": "",
                },
            }
        )
        server.GEMINI_TIMEOUT_SECONDS = 30
        server.MAX_ATTEMPTS = 3
        server.DEBUG = True

        # Keep backoff delays out of the test runtime while still recording them.
        self.sleep_patcher = patch.object(server.time, "sleep")
        self.sleep_mock = self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

    def tearDown(self):
        server.CONFIG.clear()
        server.CONFIG.update(self.saved_config)
        server.GEMINI_TIMEOUT_SECONDS = self.saved_timeout
        server.MAX_ATTEMPTS = self.saved_attempts
        server.DEBUG = self.saved_debug

    def test_request_uses_gemini_endpoint_headers_and_body(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Today I am feeling low."}]}}
                    ]
                }
            ),
        ) as urlopen:
            result = server.call_ai("aaj mera mood thoda off hai", "normal")

        self.assertEqual(result, "Today I am feeling low.")
        self.assertEqual(urlopen.call_count, 1)
        args, kwargs = urlopen.call_args
        request = args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        payload = json.loads(request.data.decode("utf-8"))

        self.assertEqual(
            request.full_url,
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(headers["x-goog-api-key"], "test-gemini-key")
        self.assertNotIn("authorization", headers)
        self.assertEqual(kwargs["timeout"], 30)

        self.assertEqual(
            payload["system_instruction"]["parts"][0]["text"], EXPECTED_SYSTEM_PROMPT
        )
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(
            payload["contents"][0]["parts"][0]["text"], "aaj mera mood thoda off hai"
        )
        self.assertEqual(payload["generationConfig"], {"maxOutputTokens": 300})
        self.assertNotIn("messages", payload)
        self.assertNotIn("thinkingConfig", payload["generationConfig"])
        self.assertNotIn("thinking_config", payload["generationConfig"])
        self.assertNotIn("reasoning_effort", payload)

    def test_payload_json_is_compact_to_reduce_request_size(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {"candidates": [{"content": {"parts": [{"text": "Done."}]}}]}
            ),
        ) as urlopen:
            server.call_ai("test", "normal")

        raw = urlopen.call_args.args[0].data
        expected = json.dumps(
            json.loads(raw.decode("utf-8")), ensure_ascii=False, separators=(",", ":")
        )
        self.assertEqual(raw.decode("utf-8"), expected)

    def test_request_and_response_details_are_logged(self):
        response_body = {
            "candidates": [{"content": {"parts": [{"text": "Logged answer."}]}}]
        }
        output = io.StringIO()

        with patch.object(
            server.urllib.request, "urlopen", return_value=FakeResponse(response_body)
        ), contextlib.redirect_stdout(output):
            result = server.call_ai("test", "normal")

        logs = output.getvalue()
        self.assertEqual(result, "Logged answer.")
        self.assertIn("model=gemini-3.5-flash-lite", logs)
        self.assertIn("payload_bytes=", logs)
        self.assertIn("timeout_seconds=30", logs)
        self.assertIn("Gemini attempt 1/3", logs)
        self.assertIn("elapsed_seconds=", logs)
        self.assertIn("Gemini response: attempt=1", logs)
        self.assertIn("status=200", logs)
        self.assertIn("Gemini response body:", logs)
        self.assertIn("Logged answer.", logs)

    def test_token_usage_is_logged_when_available(self):
        response_body = {
            "candidates": [{"content": {"parts": [{"text": "Logged usage."}]}}],
            "usageMetadata": {
                "promptTokenCount": 42,
                "candidatesTokenCount": 7,
                "totalTokenCount": 49,
            },
        }
        output = io.StringIO()

        with patch.object(
            server.urllib.request, "urlopen", return_value=FakeResponse(response_body)
        ), contextlib.redirect_stdout(output):
            server.call_ai("test", "normal")

        logs = output.getvalue()
        self.assertIn("Gemini usage:", logs)
        self.assertIn("prompt_tokens=42", logs)
        self.assertIn("output_tokens=7", logs)
        self.assertIn("total_tokens=49", logs)

    def test_http_error_logs_status_body_and_traceback(self):
        error = urllib.error.HTTPError(
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"message":"Exact Gemini failure detail"}}'),
        )
        output = io.StringIO()

        with patch.object(server.urllib.request, "urlopen", side_effect=error):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(server.ApiError) as raised:
                    server.call_ai("test", "normal")

        logs = output.getvalue()
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(
            raised.exception.message, "Gemini HTTP 400: Exact Gemini failure detail"
        )
        self.assertIn("Gemini HTTP error: attempt=1", logs)
        self.assertIn("status=400", logs)
        self.assertIn("Gemini error body:", logs)
        self.assertIn("Exact Gemini failure detail", logs)
        self.assertIn("Traceback (most recent call last):", logs)
        self.assertEqual(self.sleep_mock.call_count, 0)

    def test_timeout_logs_timeout_details_and_traceback(self):
        output = io.StringIO()

        with patch.object(server.urllib.request, "urlopen", side_effect=TimeoutError()):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(server.ApiError) as raised:
                    server.call_ai("test", "normal")

        logs = output.getvalue()
        self.assertEqual(raised.exception.status, 503)
        self.assertIn("Gemini is taking longer than usual", raised.exception.message)
        self.assertIn("Gemini timeout", raised.exception.message)
        self.assertIn("timeout_seconds=30", logs)
        self.assertIn("Traceback (most recent call last):", logs)
        self.assertEqual(self.sleep_mock.call_count, 2)

    def test_non_normal_tone_is_added_to_user_content(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {"candidates": [{"content": {"parts": [{"text": "Sir, noted."}]}}]}
            ),
        ) as urlopen:
            server.call_ai("sir, main report bhej dunga", "formal")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["contents"][0]["parts"][0]["text"],
            "Tone: formal\n\nText: sir, main report bhej dunga",
        )

    def test_multiple_response_parts_are_joined_and_trimmed(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "Sir, "}, {"text": "I will send it."}]
                            }
                        }
                    ]
                }
            ),
        ):
            result = server.call_ai("sir, bhej dunga", "formal")

        self.assertEqual(result, "Sir, I will send it.")

    def test_missing_api_key_raises_503(self):
        server.CONFIG["key"] = ""
        server.CONFIG["keys"]["gemini"] = ""
        server.CONFIG["keys"]["groq"] = ""

        with self.assertRaises(server.ApiError) as raised:
            server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("GROQ_API_KEY", raised.exception.message)

    def test_gemini_http_error_is_mapped_to_502(self):
        error = urllib.error.HTTPError(
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
            400,
            "Bad Request",
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "error": {
                            "message": "Thinking level MINIMAL is not supported for this model."
                        }
                    }
                ).encode("utf-8")
            ),
        )

        with patch.object(server.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("Thinking level MINIMAL", raised.exception.message)

    def test_network_error_is_reported_as_a_friendly_overload(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("Gemini is taking longer than usual", raised.exception.message)
        self.assertIn("Gemini connection error", raised.exception.message)

    def test_timeout_is_retried_with_exponential_backoff(self):
        with patch.object(server.urllib.request, "urlopen", side_effect=TimeoutError()) as urlopen:
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("Gemini is taking longer than usual", raised.exception.message)
        self.assertNotIn("Gemini took too long", raised.exception.message)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in self.sleep_mock.call_args_list], [1, 2])

    def test_503_is_retried_with_backoff_and_then_succeeds(self):
        overload = urllib.error.HTTPError(
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":{"message":"Model is currently experiencing high demand."}}'),
        )
        success = FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "Recovered answer."}]}}]}
        )
        output = io.StringIO()

        with patch.object(
            server.urllib.request, "urlopen", side_effect=[overload, success]
        ) as urlopen, contextlib.redirect_stdout(output):
            result = server.call_ai("test", "normal")

        logs = output.getvalue()
        self.assertEqual(result, "Recovered answer.")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(self.sleep_mock.call_args_list[0].args, (1,))
        self.assertIn("Gemini retry scheduled", logs)
        self.assertIn("backoff=exponential", logs)
        self.assertIn("attempt=1/3", logs)
        self.assertIn("attempt=2/3", logs)

    def test_retry_uses_the_lighter_fallback_model(self):
        overload = urllib.error.HTTPError(
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":{"message":"High demand"}}'),
        )
        success = FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "Fallback answer."}]}}]}
        )

        with patch.object(server.urllib.request, "urlopen", side_effect=[overload, success]) as urlopen:
            server.call_ai("test", "normal")

        first_url = urlopen.call_args_list[0].args[0].full_url
        second_url = urlopen.call_args_list[1].args[0].full_url
        self.assertIn("gemini-3.5-flash-lite", first_url)
        self.assertIn("gemini-3.1-flash-lite", second_url)

    def test_retry_after_header_is_honoured(self):
        headers = {"Retry-After": "3"}
        overload = urllib.error.HTTPError(
            "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
            429,
            "Too Many Requests",
            headers,
            io.BytesIO(b'{"error":{"message":"Rate limited"}}'),
        )
        success = FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "After waiting."}]}}]}
        )

        with patch.object(server.urllib.request, "urlopen", side_effect=[overload, success]):
            server.call_ai("test", "normal")

        self.assertEqual(self.sleep_mock.call_args_list[0].args, (3,))

    def test_all_attempts_failing_returns_a_friendly_503(self):
        error_body = b'{"error":{"message":"Model is currently experiencing high demand."}}'
        errors = [
            urllib.error.HTTPError(
                "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent",
                503,
                "Service Unavailable",
                {},
                io.BytesIO(error_body),
            )
            for _ in range(3)
        ]

        with patch.object(server.urllib.request, "urlopen", side_effect=errors) as urlopen:
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 503)
        self.assertTrue(
            raised.exception.message.startswith("Gemini is busy right now.")
        )
        self.assertIn("high demand", raised.exception.message)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in self.sleep_mock.call_args_list], [1, 2])

    def test_friendly_error_hides_details_when_debug_is_off(self):
        error = server.ApiError(503, "Gemini HTTP 503: high demand", overload=True)
        server.DEBUG = False

        friendly = server.friendly_error(error)

        self.assertEqual(friendly.status, 503)
        self.assertEqual(friendly.message, "Gemini is busy right now. Please try again in a moment.")

    def test_invalid_json_response_is_mapped_to_502(self):
        with patch.object(
            server.urllib.request, "urlopen", return_value=FakeResponse(b"not json")
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("Invalid Gemini JSON", raised.exception.message)

    def test_empty_result_is_reported(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {"candidates": [{"content": {"parts": [{"text": "  "}]}}]}
            ),
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("empty result", raised.exception.message)

    def test_blocked_prompt_reports_the_block_reason(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(
                {
                    "candidates": [],
                    "promptFeedback": {"blockReason": "SAFETY"},
                }
            ),
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("SAFETY", raised.exception.message)

    def test_unexpected_response_shape_is_reported(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse({"candidates": [{"content": None}]}),
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("Unexpected Gemini response shape", raised.exception.message)

    def test_non_dict_json_response_is_reported(self):
        with patch.object(
            server.urllib.request, "urlopen", return_value=FakeResponse([])
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("Unexpected Gemini response shape", raised.exception.message)


def chat_payload(text="Clean English answer."):
    """OpenAI-compatible chat completion response."""
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def make_http_error(status, message, url="https://api.example/v1/chat/completions", headers=None):
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError(url, status, "error", headers or {}, io.BytesIO(body))


class MultiProviderTests(unittest.TestCase):
    """Groq-first fallback chain with Gemini and OpenAI-compatible backups."""

    def setUp(self):
        self.saved_config = copy.deepcopy(server.CONFIG)
        self.saved_timeout = server.GEMINI_TIMEOUT_SECONDS
        self.saved_attempts = server.MAX_ATTEMPTS
        self.saved_debug = server.DEBUG
        server.CONFIG.update(
            {
                "key": "gemini-key",
                "base_url": "https://gemini.example/v1beta",
                "model": "gemini-3.5-flash-lite",
                "fallback_model": "gemini-3.1-flash-lite",
                "provider": "auto",
                "keys": {
                    "gemini": "gemini-key",
                    "openai": "openai-key",
                    "groq": "groq-key",
                    "openrouter": "openrouter-key",
                },
                "provider_settings": {
                    name: {
                        "base_url": server.PROVIDER_DEFAULTS[name]["base_url"],
                        "model": server.PROVIDER_DEFAULTS[name]["model"],
                    }
                    for name in server.PROVIDER_ORDER
                },
            }
        )
        server.GEMINI_TIMEOUT_SECONDS = 30
        server.MAX_ATTEMPTS = 3
        server.DEBUG = False

        self.sleep_patcher = patch.object(server.time, "sleep")
        self.sleep_mock = self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

    def tearDown(self):
        server.CONFIG.clear()
        server.CONFIG.update(self.saved_config)
        server.GEMINI_TIMEOUT_SECONDS = self.saved_timeout
        server.MAX_ATTEMPTS = self.saved_attempts
        server.DEBUG = self.saved_debug

    def test_auto_chain_is_groq_first_and_provider_names_are_normalized(self):
        self.assertEqual(
            server.provider_chain("auto"),
            ("groq", "gemini", "openai", "openrouter"),
        )
        self.assertEqual(server.normalize_provider(" OpenAI "), "openai")
        self.assertEqual(server.normalize_provider("unknown"), "auto")
        self.assertEqual(server.provider_chain("groq"), ("groq",))

    def test_auto_uses_groq_first_with_its_default_model(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("Groq translation.")),
        ) as urlopen:
            timings = {}
            result = server.call_ai("test", "normal", timings)

        self.assertEqual(result, "Groq translation.")
        self.assertEqual(timings["provider"], "groq")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://api.groq.com/openai/v1/chat/completions"
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "llama-3.3-70b-versatile")

    def test_groq_429_switches_immediately_to_gemini(self):
        errors = [make_http_error(429, "Quota exceeded")]
        responses = [
            FakeResponse(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Switched to Gemini."}]}}
                    ]
                }
            )
        ]
        output = io.StringIO()

        with patch.object(
            server.urllib.request, "urlopen", side_effect=errors + responses
        ) as urlopen, contextlib.redirect_stdout(output):
            timings = {}
            result = server.call_ai("test", "normal", timings)

        self.assertEqual(result, "Switched to Gemini.")
        self.assertEqual(timings["provider"], "gemini")
        self.assertEqual(urlopen.call_count, 2)
        self.assertIn(
            "api.groq.com/openai/v1/chat/completions",
            urlopen.call_args_list[0].args[0].full_url,
        )
        self.assertIn(
            "models/gemini-3.5-flash-lite", urlopen.call_args_list[1].args[0].full_url
        )
        self.assertIn("Provider switch: Groq failed", output.getvalue())
        self.assertIn("trying Gemini", output.getvalue())
        self.assertEqual(self.sleep_mock.call_count, 0)

    def test_groq_timeout_switches_to_gemini_without_extra_wait(self):
        gemini_response = FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "After timeout."}]}}
                ]
            }
        )
        with patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=[TimeoutError(), gemini_response],
        ) as urlopen:
            timings = {}
            result = server.call_ai("test", "normal", timings)

        self.assertEqual(result, "After timeout.")
        self.assertEqual(timings["provider"], "gemini")
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(self.sleep_mock.call_count, 0)

    def test_groq_network_error_switches_to_gemini(self):
        gemini_response = FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "Gemini answer."}]}}
                ]
            }
        )
        with patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=[urllib.error.URLError("offline"), gemini_response],
        ) as urlopen:
            timings = {}
            result = server.call_ai("test", "normal", timings)

        self.assertEqual(result, "Gemini answer.")
        self.assertEqual(timings["provider"], "gemini")
        self.assertIn("models/gemini-3.5-flash-lite", urlopen.call_args.args[0].full_url)

    def test_all_providers_failing_returns_friendly_503(self):
        offline = urllib.error.URLError("offline")
        failures = [
            make_http_error(429, "Quota exceeded"),  # Groq (primary)
            make_http_error(503, "High demand"),     # Gemini (automatic fallback)
            TimeoutError(),                          # OpenAI
            offline,                                  # OpenRouter
            offline,
            offline,  # The last provider still uses its own retry budget.
        ]

        with patch.object(
            server.urllib.request, "urlopen", side_effect=failures
        ) as urlopen:
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("try again", raised.exception.message)
        self.assertEqual(urlopen.call_count, 6)
        self.assertEqual([call.args[0] for call in self.sleep_mock.call_args_list], [1, 2])

    def test_gemini_503_uses_lighter_model_when_no_backup_key_exists(self):
        server.CONFIG["keys"]["openai"] = ""
        server.CONFIG["keys"]["groq"] = ""
        server.CONFIG["keys"]["openrouter"] = ""

        with patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=[
                make_http_error(503, "High demand"),
                FakeResponse(
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": "Recovered by Gemini."}]}}
                        ]
                    }
                ),
            ],
        ) as urlopen:
            timings = {}
            result = server.call_ai("test", "normal", timings)

        self.assertEqual(result, "Recovered by Gemini.")
        self.assertEqual(timings["provider"], "gemini")
        self.assertIn("gemini-3.1-flash-lite", urlopen.call_args.args[0].full_url)
        self.assertEqual(self.sleep_mock.call_args_list[0].args, (1,))

    def test_openai_request_uses_chat_format_bearer_key_and_shared_prompt(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("OpenAI translation.")),
        ) as urlopen:
            timings = {}
            result = server.call_ai("test", "normal", timings, provider="openai")

        self.assertEqual(result, "OpenAI translation.")
        self.assertEqual(timings["provider"], "openai")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://api.openai.com/v1/chat/completions"
        )
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], "Bearer openai-key")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["messages"][0], {
            "role": "system", "content": server.SYSTEM_PROMPT
        })
        self.assertEqual(payload["messages"][1], {
            "role": "user", "content": "test"
        })
        self.assertEqual(payload["max_tokens"], 300)
        self.assertNotIn("system_instruction", payload)

    def test_groq_and_openrouter_use_their_own_endpoints(self):
        cases = [
            ("groq", "https://api.groq.com/openai/v1/chat/completions"),
            ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
        ]
        for provider, endpoint in cases:
            with self.subTest(provider=provider), patch.object(
                server.urllib.request,
                "urlopen",
                return_value=FakeResponse(chat_payload(f"From {provider}.")),
            ) as urlopen:
                result = server.call_ai("test", "normal", {}, provider=provider)
                request = urlopen.call_args.args[0]
                self.assertEqual(result, f"From {provider}.")
                self.assertEqual(request.full_url, endpoint)
                headers = {key.lower(): value for key, value in request.header_items()}
                self.assertEqual(headers["authorization"], f"Bearer {provider}-key")

    def test_explicit_provider_does_not_call_gemini(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("Only OpenAI.")),
        ) as urlopen:
            server.call_ai("test", "normal", provider="openai")

        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("api.openai.com", urlopen.call_args.args[0].full_url)

    def test_explicit_provider_without_key_reports_its_env_variable(self):
        server.CONFIG["keys"]["groq"] = ""

        with self.assertRaises(server.ApiError) as raised:
            server.call_ai("test", "normal", provider="groq")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("GROQ_API_KEY", raised.exception.message)

    def test_tone_is_preserved_for_chat_providers(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("Formal answer.")),
        ) as urlopen:
            server.call_ai("sir, bhej dunga", "formal", provider="openai")

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            payload["messages"][1]["content"], "Tone: formal\n\nText: sir, bhej dunga"
        )

    def test_empty_chat_result_is_reported(self):
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("")),
        ):
            with self.assertRaises(server.ApiError) as raised:
                server.call_ai("test", "normal", provider="openai")

        self.assertEqual(raised.exception.status, 502)
        self.assertIn("empty result", raised.exception.message)

    def test_chat_usage_is_logged(self):
        output = io.StringIO()
        with patch.object(
            server.urllib.request,
            "urlopen",
            return_value=FakeResponse(chat_payload("Logged.")),
        ), contextlib.redirect_stdout(output):
            server.call_ai("test", "normal", provider="openai")

        logs = output.getvalue()
        self.assertIn("OpenAI usage:", logs)
        self.assertIn("prompt_tokens=10", logs)
        self.assertIn("output_tokens=5", logs)
        self.assertIn("total_tokens=15", logs)


class HandlerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_server = ThreadingHTTPServer(("127.0.0.1", 0), MockGeminiHandler)
        cls.mock_port = cls.mock_server.server_address[1]
        cls.mock_thread = threading.Thread(
            target=cls.mock_server.serve_forever, daemon=True
        )
        cls.mock_thread.start()

        cls.app_server = ThreadingHTTPServer(("127.0.0.1", 0), QuietAppHandler)
        cls.app_port = cls.app_server.server_address[1]
        cls.app_thread = threading.Thread(target=cls.app_server.serve_forever, daemon=True)
        cls.app_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.app_port}"

    @classmethod
    def tearDownClass(cls):
        cls.mock_server.shutdown()
        cls.app_server.shutdown()
        cls.mock_server.server_close()
        cls.app_server.server_close()
        cls.mock_thread.join(timeout=5)
        cls.app_thread.join(timeout=5)

    def setUp(self):
        self.saved_config = copy.deepcopy(server.CONFIG)
        self.saved_timeout = server.GEMINI_TIMEOUT_SECONDS
        self.saved_attempts = server.MAX_ATTEMPTS
        self.saved_debug = server.DEBUG
        MockGeminiHandler.status = 200
        MockGeminiHandler.payload = {
            "candidates": [
                {"content": {"parts": [{"text": "Today I am feeling a little low."}]}}
            ]
        }
        MockGeminiHandler.responses.clear()
        MockGeminiHandler.requests.clear()
        server.CONFIG.update(
            {
                "key": "test-gemini-key",
                "base_url": f"http://127.0.0.1:{self.mock_port}/v1beta",
                "model": "gemini-3.5-flash-lite",
                "fallback_model": "gemini-3.1-flash-lite",
                "provider": "auto",
                "keys": {
                    "gemini": "test-gemini-key",
                    "openai": "",
                    "groq": "",
                    "openrouter": "",
                },
            }
        )
        server.GEMINI_TIMEOUT_SECONDS = 30
        server.MAX_ATTEMPTS = 3
        server.DEBUG = True

        self.sleep_patcher = patch.object(server.time, "sleep")
        self.sleep_patcher.start()
        self.addCleanup(self.sleep_patcher.stop)

    def tearDown(self):
        server.CONFIG.clear()
        server.CONFIG.update(self.saved_config)
        server.GEMINI_TIMEOUT_SECONDS = self.saved_timeout
        server.MAX_ATTEMPTS = self.saved_attempts
        server.DEBUG = self.saved_debug

    def send_request(self, path, method="GET", payload=None, raw=None, with_headers=False):
        if raw is not None:
            data = raw.encode("utf-8")
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
        else:
            data = None

        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body, headers = response.status, response.read().decode("utf-8"), response.headers
        except urllib.error.HTTPError as error:
            status, body, headers = error.code, error.read().decode("utf-8"), error.headers

        if with_headers:
            return status, body, headers
        return status, body

    def test_health_endpoint_returns_ok(self):
        status, body = self.send_request("/api/health")
        data = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(data, {"status": "ok"})

    def test_health_endpoint_returns_ok_even_when_keys_missing(self):
        # Health endpoint is always available; just verify status ok.
        # (No-op: the /api/health route does not require any keys.)

        status, body = self.send_request("/api/health")
        data = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(data, {"status": "ok"})

    def test_convert_endpoint_works_end_to_end_against_mock_gemini(self):
        status, body = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "aaj mera mood thoda off hai", "tone": "normal"},
        )
        data = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(data["text"], "Today I am feeling a little low.")
        self.assertEqual(len(MockGeminiHandler.requests), 1)

        gemini_request = MockGeminiHandler.requests[0]
        self.assertEqual(
            gemini_request["path"], "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        )
        self.assertEqual(gemini_request["headers"]["x-goog-api-key"], "test-gemini-key")
        self.assertEqual(
            gemini_request["body"]["system_instruction"]["parts"][0]["text"],
            EXPECTED_SYSTEM_PROMPT,
        )
        self.assertEqual(
            gemini_request["body"]["generationConfig"], {"maxOutputTokens": 300}
        )
        self.assertNotIn("thinkingConfig", gemini_request["body"]["generationConfig"])

    def test_convert_response_includes_timing_headers(self):
        status, body, headers = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal"},
            with_headers=True,
        )

        self.assertEqual(status, 200)
        self.assertRegex(headers.get("X-Response-Time-Ms"), r"^\d+$")
        self.assertRegex(headers.get("Server-Timing"), r"^app;dur=\d+$")

    def test_convert_response_includes_cors_headers(self):
        status, body, headers = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal"},
            with_headers=True,
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(headers.get("Access-Control-Allow-Methods"), "POST, OPTIONS")
        self.assertEqual(headers.get("Access-Control-Allow-Headers"), "Content-Type")

    def test_convert_options_preflight_returns_cors_headers(self):
        status, body, headers = self.send_request(
            "/api/convert", method="OPTIONS", with_headers=True
        )

        self.assertEqual(status, 204)
        self.assertEqual(body, "")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertEqual(headers.get("Access-Control-Allow-Methods"), "POST, OPTIONS")
        self.assertEqual(headers.get("Access-Control-Allow-Headers"), "Content-Type")

    def test_convert_response_reports_the_provider_that_answered(self):
        status, body = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["provider"], "gemini")

    def test_convert_response_can_report_a_fallback_provider(self):
        def fake_call_ai(text, tone, timings=None, provider=None):
            timings["provider"] = "openai"
            return "Answer from OpenAI."

        with patch.object(server, "call_ai", side_effect=fake_call_ai):
            status, body = self.send_request(
                "/api/convert",
                method="POST",
                payload={
                    "text": "test",
                    "tone": "normal",
                    "provider": "openai",
                },
            )

        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["text"], "Answer from OpenAI.")
        self.assertEqual(data["provider"], "openai")

    def test_unknown_provider_in_request_is_treated_as_auto(self):
        status, body = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal", "provider": "unknown"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["provider"], "gemini")
        self.assertEqual(len(MockGeminiHandler.requests), 1)

    def test_empty_text_is_rejected_before_calling_gemini(self):
        status, body = self.send_request(
            "/api/convert", method="POST", payload={"text": "   ", "tone": "normal"}
        )

        self.assertEqual(status, 400)
        self.assertIn("Please enter some Hinglish text", json.loads(body)["error"])
        self.assertEqual(len(MockGeminiHandler.requests), 0)

    def test_new_ui_tones_are_accepted(self):
        for tone in ("casual", "professional", "polite", "direct", "empathetic"):
            with self.subTest(tone=tone):
                status, body = self.send_request(
                    "/api/convert",
                    method="POST",
                    payload={"text": "test", "tone": tone},
                )
                self.assertEqual(status, 200, body)

    def test_invalid_tone_is_rejected(self):
        status, body = self.send_request(
            "/api/convert", method="POST", payload={"text": "test", "tone": "angry"}
        )

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "Unknown tone selection.")
        self.assertEqual(len(MockGeminiHandler.requests), 0)

    def test_invalid_json_is_rejected(self):
        status, body = self.send_request(
            "/api/convert", method="POST", raw="not-json"
        )

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "Request must be valid JSON.")

    def test_non_object_json_is_rejected(self):
        status, body = self.send_request("/api/convert", method="POST", raw="[]")

        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "Request must be a JSON object.")

    def test_missing_key_returns_503(self):
        server.CONFIG["key"] = ""
        server.CONFIG["keys"]["gemini"] = ""
        server.CONFIG["keys"]["groq"] = ""

        status, body = self.send_request(
            "/api/convert", method="POST", payload={"text": "test", "tone": "normal"}
        )

        self.assertEqual(status, 503)
        self.assertIn("GROQ_API_KEY", json.loads(body)["error"])

    def test_gemini_error_is_passed_to_the_browser_as_502(self):
        MockGeminiHandler.status = 400
        MockGeminiHandler.payload = {
            "error": {"message": "Thinking level MINIMAL is not supported for this model."}
        }

        status, body = self.send_request(
            "/api/convert", method="POST", payload={"text": "test", "tone": "normal"}
        )
        data = json.loads(body)

        self.assertEqual(status, 502)
        self.assertTrue(data["error"].startswith("Gemini HTTP 400:"))
        self.assertIn("Thinking level MINIMAL", data["error"])

    def test_overload_is_retried_with_fallback_model_end_to_end(self):
        MockGeminiHandler.responses.extend(
            [
                (503, {"error": {"message": "Model is currently experiencing high demand."}}),
                (
                    200,
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": "Recovered by fallback."}]}}
                        ]
                    },
                ),
            ]
        )

        status, body = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal"},
        )
        data = json.loads(body)

        self.assertEqual(status, 200)
        self.assertEqual(data["text"], "Recovered by fallback.")
        self.assertEqual(len(MockGeminiHandler.requests), 2)
        self.assertIn("gemini-3.1-flash-lite", MockGeminiHandler.requests[1]["path"])

    def test_persistent_overload_returns_a_friendly_503_end_to_end(self):
        MockGeminiHandler.responses.extend(
            (503, {"error": {"message": "Model is currently experiencing high demand."}})
            for _ in range(3)
        )

        status, body = self.send_request(
            "/api/convert",
            method="POST",
            payload={"text": "test", "tone": "normal"},
        )
        data = json.loads(body)

        self.assertEqual(status, 503)
        self.assertIn("Gemini is busy right now", data["error"])
        self.assertEqual(len(MockGeminiHandler.requests), 3)

    def test_unknown_post_route_returns_404(self):
        status, body = self.send_request(
            "/api/unknown", method="POST", payload={"text": "test"}
        )

        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "Not found.")

    def test_static_index_is_served(self):
        status, body = self.send_request("/")

        self.assertEqual(status, 200)
        self.assertIn("BolBindaas", body)
        self.assertIn('id="convertBtn"', body)


if __name__ == "__main__":
    unittest.main()
