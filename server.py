"""BolBindaas — static file server + one AI proxy route.

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
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
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


def call_ai(text: str, tone: str) -> str:
    """Send the text to an OpenAI-compatible chat endpoint and return English."""
    if not CONFIG["key"]:
        raise ApiError(
            503,
            "AI API key is not configured. Add AI_API_KEY to .env and restart the server.",
        )

    # The tone is an instruction layered on top of the fixed system prompt.
    user_content = text if tone == "normal" else f"Tone: {tone}\n\nText: {text}"
    payload = {
        "model": CONFIG["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.4,
        "max_tokens": 1200,
    }

    request = urllib.request.Request(
        CONFIG["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONFIG['key']}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:200]
        raise ApiError(502, f"AI provider returned {error.code}. {detail}") from error
    except urllib.error.URLError as error:
        raise ApiError(504, f"Could not reach the AI provider: {error.reason}") from error
    except TimeoutError as error:
        raise ApiError(504, "The AI provider took too long. Please try again.") from error
    except json.JSONDecodeError as error:
        raise ApiError(502, "AI provider returned invalid JSON.") from error

    try:
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content", "")
    except (IndexError, AttributeError, TypeError) as error:
        raise ApiError(502, "Unexpected response shape from the AI provider.") from error

    # Some providers return content as a list of {type, text} parts.
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    if not isinstance(content, str) or not content.strip():
        raise ApiError(502, "The AI provider returned an empty result.")

    return content.strip()


class AppHandler(SimpleHTTPRequestHandler):
    """Serve static files, plus /api/health and POST /api/convert."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self.send_json(200, {"status": "ok", "configured": bool(CONFIG["key"])})
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
    load_env()
    CONFIG["key"] = os.getenv("AI_API_KEY", "").strip()
    CONFIG["base_url"] = os.getenv("AI_BASE_URL", CONFIG["base_url"]).strip()
    CONFIG["model"] = os.getenv("AI_MODEL", CONFIG["model"]).strip()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5500"))

    print(f"Serving {ROOT} at http://{host}:{port}")
    print("AI key loaded." if CONFIG["key"] else "AI key missing — set AI_API_KEY in .env")
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    main()
