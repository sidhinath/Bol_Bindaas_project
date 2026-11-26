"""BolBindaas — static file server + one Gemini proxy route.

Uses only the Python standard library, so there are no packages to install.
The frontend calls POST /api/convert; this file is the only place that reads
the API key, from the environment (or a local .env file).
"""

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_CHARS = 4000

# Gemini REST endpoint: POST /v1beta/models/{model}:generateContent
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"

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


class ApiError(Exception):
    """An error with an HTTP status safe to send back to the browser."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


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
        print("Ignoring old OpenAI AI_BASE_URL; using the Gemini endpoint.")
        base_url = DEFAULT_BASE_URL
    CONFIG["base_url"] = base_url or DEFAULT_BASE_URL

    model = os.getenv("AI_MODEL", DEFAULT_MODEL).strip()
    if model.lower().startswith(("gpt-", "o1", "o3", "o4")):
        print(f"Ignoring old OpenAI AI_MODEL={model!r}; using {DEFAULT_MODEL}.")
        model = DEFAULT_MODEL
    CONFIG["model"] = model or DEFAULT_MODEL


def call_ai(text: str, tone: str) -> str:
    """Send the text to Gemini generateContent and return English."""
    if not CONFIG["key"]:
        raise ApiError(
            503,
            "Gemini API key is not configured. Add AI_API_KEY to .env and restart "
            "the server (or set it in the hosting platform).",
        )

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
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": CONFIG["key"],
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        detail = body
        try:
            parsed = json.loads(body)
            detail = parsed.get("error", {}).get("message") or body
        except (json.JSONDecodeError, AttributeError):
            pass
        detail = detail[:200]
        if error.code in (400, 401, 403):
            raise ApiError(
                502,
                "Gemini rejected the request. Check that AI_API_KEY is a valid "
                f"Gemini API key and AI_MODEL is a Gemini model. Details: {detail}",
            ) from error
        raise ApiError(502, f"Gemini returned {error.code}. {detail}") from error
    except urllib.error.URLError as error:
        raise ApiError(504, f"Could not reach Gemini: {error.reason}") from error
    except TimeoutError as error:
        raise ApiError(504, "Gemini took too long. Please try again.") from error
    except json.JSONDecodeError as error:
        raise ApiError(502, "Gemini returned invalid JSON.") from error

    try:
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") or []
        content = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        )
    except (IndexError, AttributeError, TypeError) as error:
        raise ApiError(502, "Unexpected response shape from Gemini.") from error

    if not content.strip():
        feedback = data.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            raise ApiError(502, f"Gemini blocked the prompt ({reason}). Please rephrase it.")
        raise ApiError(502, "Gemini returned an empty result.")

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
            self.send_json(error.status, {"error": error.message})
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

    print(f"Serving {ROOT} at http://{host}:{port}")
    print(f"AI provider: Gemini ({CONFIG['model']})")
    print("Gemini key loaded." if CONFIG["key"] else "Gemini key missing — set AI_API_KEY in .env")
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    main()
