"""BolBindaas — static file server + one Gemini proxy route.

Uses only the Python standard library, so there are no packages to install.
The frontend calls POST /api/convert; this file is the only place that reads
the API key, from the environment (or a local .env file).
"""

import json
import os
import time
import traceback
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_CHARS = 4000

# Gemini REST endpoint: POST /v1beta/models/{model}:generateContent
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_TIMEOUT_SECONDS = 90

# System prompt is kept server-side and sent verbatim with every request.
SYSTEM_PROMPT = (
    "You are a Hinglish-to-English writer. The user will give text in Hinglish "
    "(Hindi in Roman script mixed with English). Rewrite it as clear, natural, "
    "grammatically correct English that preserves the exact meaning, emotion, "
    "and tone. Output ONLY the English text, with no explanations, no quotes, "
    "no preamble."
)

ALLOWED_TONES = {"normal", "formal", "casual", "poetic"}
CONFIG = {
    "key": "",
    "base_url": DEFAULT_BASE_URL,
    "model": DEFAULT_MODEL,
}

# Debug mode is on by default while diagnosing the live Gemini failures.
# Set AI_DEBUG=0 to switch back to shorter, user-facing messages later.
DEBUG = True


class ApiError(Exception):
    """An error with an HTTP status safe to send back to the browser."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def log(message: str) -> None:
    """Write immediately so Render captures lines before a worker restarts."""
    print(message, flush=True)


def log_exception(label: str, error: BaseException) -> None:
    """Print an exception and its full traceback to the platform logs."""
    log(f"{label}: {type(error).__name__}: {error}")
    log(traceback.format_exc())


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def error_message_from_body(body: str) -> str:
    """Extract Gemini's exact error message, falling back to the raw body."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(parsed, dict):
        detail = parsed.get("error")
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if parsed.get("message"):
            return str(parsed["message"])
    return body


def load_env() -> None:
    """Read simple KEY=VALUE lines from .env without extra dependencies."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment variables (set by a hosting platform) win over .env.
        if key and key not in os.environ:
            os.environ[key] = value


def configure() -> None:
    """Load AI settings, tolerating leftover OpenAI values from older deploys."""
    global DEBUG

    load_env()

    key = (
        os.getenv("AI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    )
    CONFIG["key"] = key.strip()

    base_url = os.getenv("AI_BASE_URL", DEFAULT_BASE_URL).strip()
    if "openai" in base_url.lower():
        log("Ignoring old OpenAI AI_BASE_URL; using the Gemini endpoint.")
        base_url = DEFAULT_BASE_URL
    CONFIG["base_url"] = base_url or DEFAULT_BASE_URL

    model = os.getenv("AI_MODEL", DEFAULT_MODEL).strip()
    if model.lower().startswith(("gpt-", "o1", "o3", "o4")):
        log(f"Ignoring old OpenAI AI_MODEL={model!r}; using {DEFAULT_MODEL}.")
        model = DEFAULT_MODEL
    CONFIG["model"] = model or DEFAULT_MODEL

    DEBUG = env_flag("AI_DEBUG", True)
    log(
        "Gemini config: "
        f"model={CONFIG['model']} "
        f"base_url={CONFIG['base_url']} "
        f"debug={DEBUG} "
        f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )


def call_ai(text: str, tone: str) -> str:
    """Send the text to Gemini generateContent and return English."""
    started = time.monotonic()

    if not CONFIG["key"]:
        message = (
            "Gemini API key is not configured. Add AI_API_KEY to .env and restart "
            "the server (or set it in the hosting platform)."
        )
        log(f"Gemini error: {message}")
        raise ApiError(503, message)

    # The tone is an instruction layered on top of the fixed system prompt.
    user_content = text if tone == "normal" else f"Tone: {tone}\n\nText: {text}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {"maxOutputTokens": 1200},
    }

    endpoint = (
        f"{CONFIG['base_url'].rstrip('/')}/models/{CONFIG['model']}:generateContent"
    )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": CONFIG["key"],
        },
        method="POST",
    )

    log(
        f"Gemini request: model={CONFIG['model']} endpoint={endpoint} "
        f"payload_bytes={len(body)} timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )
    log(f"Gemini request payload: {body.decode('utf-8')}")

    raw_response = None
    response_status = None

    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            response_status = getattr(response, "status", None)
            raw_response = response.read().decode("utf-8", errors="replace")
            log(
                f"Gemini response: status={response_status} "
                f"response_bytes={len(raw_response.encode('utf-8'))} "
                f"elapsed_seconds={time.monotonic() - started:.2f}"
            )
            log(f"Gemini response body: {raw_response}")
            data = json.loads(raw_response)
    except urllib.error.HTTPError as error:
        raw_response = error.read().decode("utf-8", errors="replace")
        response_status = error.code
        headers = dict(error.headers.items()) if error.headers else {}
        log(
            f"Gemini HTTP error: status={response_status} reason={error.reason!r} "
            f"elapsed_seconds={time.monotonic() - started:.2f} headers={headers}"
        )
        log(f"Gemini error body: {raw_response}")
        log_exception("Gemini HTTPError", error)
        detail = error_message_from_body(raw_response)
        raise ApiError(502, f"Gemini HTTP {response_status}: {detail}") from error
    except urllib.error.URLError as error:
        log(
            f"Gemini connection error: elapsed_seconds={time.monotonic() - started:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
        )
        log_exception("Gemini URLError", error)
        raise ApiError(
            504,
            f"Gemini connection error after {time.monotonic() - started:.2f}s "
            f"(timeout={GEMINI_TIMEOUT_SECONDS}s): {error.reason!r}",
        ) from error
    except TimeoutError as error:
        log(
            f"Gemini timeout: elapsed_seconds={time.monotonic() - started:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS} endpoint={endpoint}"
        )
        log_exception("Gemini TimeoutError", error)
        raise ApiError(
            504,
            f"Gemini timeout after {time.monotonic() - started:.2f}s "
            f"(configured timeout={GEMINI_TIMEOUT_SECONDS}s): {error!r}",
        ) from error
    except json.JSONDecodeError as error:
        log_exception("Gemini JSON decode error", error)
        log(f"Gemini invalid response body: {raw_response}")
        raise ApiError(
            502,
            f"Invalid Gemini JSON after {time.monotonic() - started:.2f}s: {error}. "
            f"Response: {raw_response}",
        ) from error

    full_response = json.dumps(data, ensure_ascii=False)

    if not isinstance(data, dict):
        log(f"Gemini unexpected response shape: {full_response}")
        raise ApiError(502, f"Unexpected Gemini response shape: {full_response}")

    # A blocked prompt can arrive with no candidates at all, so check feedback
    # before indexing into candidates.
    reason = (data.get("promptFeedback") or {}).get("blockReason")
    if reason:
        log(f"Gemini blocked prompt: reason={reason} response={full_response}")
        raise ApiError(
            502, f"Gemini blocked the prompt ({reason}). Full response: {full_response}"
        )

    try:
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") or []
        content = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        )
    except (IndexError, AttributeError, TypeError) as error:
        log_exception("Gemini response parse error", error)
        log(f"Gemini unexpected response shape: {full_response}")
        raise ApiError(502, f"Unexpected Gemini response shape: {full_response}") from error

    if not content.strip():
        log(f"Gemini empty result: {full_response}")
        raise ApiError(502, f"Gemini returned an empty result. Full response: {full_response}")

    log(
        f"Gemini success: model={CONFIG['model']} "
        f"elapsed_seconds={time.monotonic() - started:.2f} "
        f"output_chars={len(content.strip())}"
    )
    return content.strip()


class AppHandler(SimpleHTTPRequestHandler):
    """Serve static files, plus /api/health and POST /api/convert."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "configured": bool(CONFIG["key"]),
                    "provider": "gemini",
                    "model": CONFIG["model"],
                },
            )
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/convert":
            self.send_json(404, {"error": "Not found."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid request length."})
            return

        if length <= 0:
            self.send_json(400, {"error": "Empty request."})
            return
        if length > 64_000:
            self.send_json(413, {"error": "Request is too large."})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Request must be valid JSON."})
            return

        if not isinstance(payload, dict):
            self.send_json(400, {"error": "Request must be a JSON object."})
            return

        text = payload.get("text")
        tone = payload.get("tone", "normal")

        if not isinstance(text, str) or not text.strip():
            self.send_json(400, {"error": "Please enter some Hinglish text."})
            return
        if len(text) > MAX_CHARS:
            self.send_json(400, {"error": f"Please keep your text under {MAX_CHARS} characters."})
            return
        if tone not in ALLOWED_TONES:
            self.send_json(400, {"error": "Unknown tone selection."})
            return

        try:
            result = call_ai(text.strip(), tone)
        except ApiError as error:
            log(f"/api/convert failed: status={error.status} message={error.message}")
            log_exception("ApiError returned to /api/convert", error)
            self.send_json(error.status, {"error": error.message})
            return
        except Exception as error:  # noqa: BLE001 - debugging live failures
            log_exception("Unexpected /api/convert error", error)
            self.send_json(
                500,
                {"error": str(error) if DEBUG else "Internal server error."},
            )
            return

        self.send_json(200, {"text": result})

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    configure()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5500"))

    log(f"Serving {ROOT} at http://{host}:{port}")
    log(f"AI provider: Gemini ({CONFIG['model']})")
    log("Gemini key loaded." if CONFIG["key"] else "Gemini key missing — set AI_API_KEY in .env")
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    main()
