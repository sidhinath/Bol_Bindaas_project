"""BolBindaas — static file server + multi-provider AI proxy.

Uses only the Python standard library, so there are no packages to install.
The frontend calls POST /api/convert; this file is the only place that reads
API keys, from the environment (or a local .env file). Gemini is the primary
provider; OpenAI, Groq, and OpenRouter are optional automatic fallbacks.
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
# Fastest Gemini tier, recommended for translation/summarization. It uses
# minimal thinking by default, so no unsupported thinkingConfig is sent.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODEL = "gemini-3.1-flash-lite"
# Legacy Flash tiers are much slower for this translation-style workload.
LEGACY_MODELS = {"gemini-3.8-flash", "gemini-3.6-flash"}
MAX_OUTPUT_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1
MAX_RETRY_DELAY_SECONDS = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
TEMPORARY_STATUS_CODES = {429, 500, 502, 503, 504}

# Provider names and the Auto order. Gemini is always tried first.
PROVIDER_GEMINI = "gemini"
PROVIDER_OPENAI = "openai"
PROVIDER_GROQ = "groq"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_AUTO = "auto"
PROVIDER_ORDER = (PROVIDER_GEMINI, PROVIDER_OPENAI, PROVIDER_GROQ, PROVIDER_OPENROUTER)
ALLOWED_PROVIDERS = {PROVIDER_AUTO, *PROVIDER_ORDER}
PROVIDER_LABELS = {
    PROVIDER_GEMINI: "Gemini",
    PROVIDER_OPENAI: "OpenAI",
    PROVIDER_GROQ: "Groq",
    PROVIDER_OPENROUTER: "OpenRouter",
}

# Defaults for OpenAI-compatible providers (all use /chat/completions).
PROVIDER_DEFAULTS = {
    PROVIDER_GEMINI: {
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "key_env": "GEMINI_API_KEY",
    },
    PROVIDER_OPENAI: {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    PROVIDER_GROQ: {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
        "key_env": "GROQ_API_KEY",
    },
    PROVIDER_OPENROUTER: {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "key_env": "OPENROUTER_API_KEY",
    },
}

# AI_API_KEY is kept first for older deployments that used it for Gemini.
KEY_ENV_VARS = {
    PROVIDER_GEMINI: ("AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    PROVIDER_OPENAI: ("OPENAI_API_KEY",),
    PROVIDER_GROQ: ("GROQ_API_KEY",),
    PROVIDER_OPENROUTER: ("OPENROUTER_API_KEY",),
}
MODEL_ENV_VARS = {
    PROVIDER_OPENAI: "OPENAI_MODEL",
    PROVIDER_GROQ: "GROQ_MODEL",
    PROVIDER_OPENROUTER: "OPENROUTER_MODEL",
}
BASE_URL_ENV_VARS = {
    PROVIDER_OPENAI: "OPENAI_BASE_URL",
    PROVIDER_GROQ: "GROQ_BASE_URL",
    PROVIDER_OPENROUTER: "OPENROUTER_BASE_URL",
}

GEMINI_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
MAX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS

# Short instruction that keeps every quality constraint but removes filler.
# The exact same instruction is used for every provider.
SYSTEM_PROMPT = (
    "Rewrite Hinglish (Hindi in Roman script mixed with English) as clear, "
    "natural, grammatically correct English. Preserve the exact meaning, "
    "emotion, and tone. Output only the English text — no explanations, "
    "quotes, or preamble."
)

ALLOWED_TONES = {"normal", "formal", "casual", "poetic"}
CONFIG = {
    # Legacy Gemini-only fields are kept so existing deployments/tests work.
    "key": "",
    "base_url": DEFAULT_BASE_URL,
    "model": DEFAULT_MODEL,
    "fallback_model": DEFAULT_FALLBACK_MODEL,
    # New multi-provider fields.
    "provider": PROVIDER_AUTO,
    "keys": {name: "" for name in PROVIDER_ORDER},
    "provider_settings": {
        name: {
            "base_url": PROVIDER_DEFAULTS[name]["base_url"],
            "model": PROVIDER_DEFAULTS[name]["model"],
        }
        for name in PROVIDER_ORDER
    },
}

# Browser responses are user-friendly by default. Set AI_DEBUG=1 to append the
# raw provider error text; server logs always keep the full error and traceback.
DEBUG = False


class ApiError(Exception):
    """An error with an HTTP status safe to send back to the browser."""

    def __init__(
        self,
        status: int,
        message: str,
        retryable: bool = False,
        overload: bool = False,
        headers: dict | None = None,
        switch_provider: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retryable = retryable
        self.overload = overload
        self.headers = headers or {}
        # True for 429/503/timeout/network errors: Auto mode may try another provider.
        self.switch_provider = switch_provider


def log(message: str) -> None:
    """Write immediately so Render captures lines before a worker restarts."""
    print(message, flush=True)


def log_exception(label: str, error: BaseException) -> None:
    """Print an exception and its full traceback to the platform logs."""
    log(f"{label}: {type(error).__name__}: {error}")
    log(traceback.format_exc())


def log_usage(data: dict, provider: str = PROVIDER_GEMINI) -> None:
    """Report token counts when the API supplies usage metadata."""
    label = PROVIDER_LABELS.get(provider, provider.title())
    usage = None
    if isinstance(data, dict):
        usage = data.get("usageMetadata") or data.get("usage")
    if not isinstance(usage, dict):
        return
    prompt = usage.get("promptTokenCount", usage.get("prompt_tokens", "?"))
    output = usage.get("candidatesTokenCount", usage.get("completion_tokens", "?"))
    total = usage.get("totalTokenCount", usage.get("total_tokens", "?"))
    log(
        f"{label} usage: "
        f"prompt_tokens={prompt} output_tokens={output} total_tokens={total}"
    )


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        number = int(value.strip())
    except (AttributeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def error_message_from_body(body: str) -> str:
    """Extract an API error message, falling back to the raw body."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(parsed, dict):
        detail = parsed.get("error")
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if isinstance(parsed.get("detail"), str):
            return parsed["detail"]
        if parsed.get("message"):
            return str(parsed["message"])
    return body


def retry_delay(attempt: int, headers: dict | None = None) -> int:
    """Exponential backoff, raised to the API's Retry-After when present."""
    delay = min(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_RETRY_DELAY_SECONDS)
    headers = headers or {}
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            delay = max(delay, min(int(retry_after), MAX_RETRY_DELAY_SECONDS))
        except (TypeError, ValueError):
            pass
    return delay


def model_for_attempt(attempt: int) -> str:
    """Use the configured Gemini model first, then a lighter fallback."""
    models = [CONFIG["model"]]
    fallback = CONFIG.get("fallback_model")
    if fallback and fallback not in models:
        models.append(fallback)
    return models[min(attempt - 1, len(models) - 1)]


def normalize_provider(value) -> str:
    """Return a valid provider name, defaulting to Auto."""
    name = str(value or PROVIDER_AUTO).strip().lower()
    return name if name in ALLOWED_PROVIDERS else PROVIDER_AUTO


def provider_key(name: str) -> str:
    """Return the configured key for a provider."""
    return CONFIG.get("keys", {}).get(name, "")


def provider_setting(name: str, field: str) -> str:
    """Return a provider endpoint/model, honouring legacy Gemini config."""
    if name == PROVIDER_GEMINI and field in ("base_url", "model"):
        legacy = CONFIG.get(field)
        if legacy:
            return legacy
    settings = CONFIG.get("provider_settings", {}).get(name, {})
    return settings.get(field) or PROVIDER_DEFAULTS[name][field]


def provider_chain(requested: str) -> tuple:
    """Providers to try: Auto uses the fixed Gemini-first order."""
    if requested == PROVIDER_AUTO:
        return PROVIDER_ORDER
    return (requested,)


def configured_providers() -> list:
    """List providers that have a key configured, in Auto order."""
    return [name for name in PROVIDER_ORDER if provider_key(name)]


def friendly_error(error: ApiError, provider: str = PROVIDER_GEMINI) -> ApiError:
    """Turn temporary provider failures into a calm, actionable browser message."""
    if not error.overload:
        return error

    label = PROVIDER_LABELS.get(provider, provider.title())
    if error.status == 504 or "timeout" in error.message.lower():
        message = f"{label} is taking longer than usual. Please try again in a moment."
    else:
        message = f"{label} is busy right now. Please try again in a moment."

    if DEBUG:
        message += f" Details: {error.message}"
    friendly = ApiError(503, message)
    friendly.switch_provider = error.switch_provider
    return friendly


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
    global DEBUG, GEMINI_TIMEOUT_SECONDS, MAX_ATTEMPTS

    load_env()

    # Keys: AI_API_KEY still works for Gemini so existing deployments survive.
    keys = {}
    for name in PROVIDER_ORDER:
        value = ""
        for variable in KEY_ENV_VARS[name]:
            value = os.getenv(variable, "").strip()
            if value:
                break
        keys[name] = value
    CONFIG["keys"] = keys
    CONFIG["key"] = keys[PROVIDER_GEMINI]

    raw_provider = (
        os.getenv("AI_PROVIDER") or os.getenv("PROVIDER") or PROVIDER_AUTO
    ).strip().lower()
    provider = normalize_provider(raw_provider)
    if raw_provider not in ALLOWED_PROVIDERS:
        log(f"Ignoring unknown AI_PROVIDER={raw_provider!r}; using {PROVIDER_AUTO}.")
    CONFIG["provider"] = provider

    base_url = os.getenv("AI_BASE_URL", DEFAULT_BASE_URL).strip()
    if "openai" in base_url.lower():
        log("Ignoring old OpenAI AI_BASE_URL; using the Gemini endpoint.")
        base_url = DEFAULT_BASE_URL
    CONFIG["base_url"] = base_url or DEFAULT_BASE_URL

    model = os.getenv("AI_MODEL", DEFAULT_MODEL).strip()
    if model.lower().startswith(("gpt-", "o1", "o3", "o4")):
        log(f"Ignoring old OpenAI AI_MODEL={model!r}; using {DEFAULT_MODEL}.")
        model = DEFAULT_MODEL
    elif model.lower() in LEGACY_MODELS and not env_flag("AI_ALLOW_LEGACY_MODEL", False):
        log(
            f"Switching slow legacy AI_MODEL={model!r} to {DEFAULT_MODEL} "
            "for faster translation. Set AI_ALLOW_LEGACY_MODEL=1 to keep it."
        )
        model = DEFAULT_MODEL
    CONFIG["model"] = model or DEFAULT_MODEL

    fallback = os.getenv("AI_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL).strip()
    if fallback.lower().startswith(("gpt-", "o1", "o3", "o4")):
        log(f"Ignoring old OpenAI AI_FALLBACK_MODEL={fallback!r}.")
        fallback = DEFAULT_FALLBACK_MODEL
    CONFIG["fallback_model"] = fallback or DEFAULT_FALLBACK_MODEL
    if CONFIG["fallback_model"] == CONFIG["model"]:
        CONFIG["fallback_model"] = ""

    settings = {}
    for name in PROVIDER_ORDER:
        defaults = PROVIDER_DEFAULTS[name]
        selected_base = defaults["base_url"]
        selected_model = defaults["model"]
        if name != PROVIDER_GEMINI:
            selected_base = os.getenv(BASE_URL_ENV_VARS[name], "").strip() or selected_base
            model_env = os.getenv(MODEL_ENV_VARS[name], "").strip()
            if model_env:
                selected_model = model_env
        settings[name] = {"base_url": selected_base, "model": selected_model}
    settings[PROVIDER_GEMINI]["base_url"] = CONFIG["base_url"]
    settings[PROVIDER_GEMINI]["model"] = CONFIG["model"]
    CONFIG["provider_settings"] = settings

    GEMINI_TIMEOUT_SECONDS = env_int(
        "AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, 5, 120
    )
    MAX_ATTEMPTS = env_int("AI_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS, 1, 5)
    DEBUG = env_flag("AI_DEBUG", False)

    log(
        "AI config: "
        f"provider={provider} "
        f"configured={','.join(configured_providers()) or 'none'} "
        f"gemini_model={CONFIG['model']} "
        f"fallback_model={CONFIG['fallback_model'] or 'none'} "
        f"attempts={MAX_ATTEMPTS} "
        f"debug={DEBUG} "
        f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )


def call_gemini_once(
    body: bytes, model: str, attempt: int, overall_started: float
) -> dict:
    """Make one Gemini request. Temporary failures are marked switchable."""
    attempt_started = time.monotonic()
    endpoint = f"{CONFIG['base_url'].rstrip('/')}/models/{model}:generateContent"
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
        f"Gemini attempt {attempt}/{MAX_ATTEMPTS}: model={model} "
        f"endpoint={endpoint} payload_bytes={len(body)} "
        f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )
    if DEBUG:
        log(f"Gemini request payload: {body.decode('utf-8')}")

    raw_response = None
    response_status = None

    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            response_status = getattr(response, "status", None)
            raw_response = response.read().decode("utf-8", errors="replace")
            log(
                f"Gemini response: attempt={attempt} model={model} "
                f"status={response_status} "
                f"response_bytes={len(raw_response.encode('utf-8'))} "
                f"elapsed_seconds={time.monotonic() - attempt_started:.2f}"
            )
            log(f"Gemini response body: {raw_response}")
            data = json.loads(raw_response)
            log_usage(data, PROVIDER_GEMINI)
            return data
    except urllib.error.HTTPError as error:
        raw_response = error.read().decode("utf-8", errors="replace")
        response_status = error.code
        headers = dict(error.headers.items()) if error.headers else {}
        log(
            f"Gemini HTTP error: attempt={attempt} model={model} "
            f"status={response_status} reason={error.reason!r} "
            f"elapsed_seconds={time.monotonic() - attempt_started:.2f} "
            f"headers={headers}"
        )
        log(f"Gemini error body: {raw_response}")
        log_exception("Gemini HTTPError", error)
        detail = error_message_from_body(raw_response)
        temporary = response_status in TEMPORARY_STATUS_CODES
        browser_status = 503 if response_status in (429, 503) else 502
        raise ApiError(
            browser_status,
            f"Gemini HTTP {response_status}: {detail}",
            retryable=response_status in RETRYABLE_STATUS_CODES,
            overload=temporary,
            headers=headers,
            switch_provider=temporary,
        ) from error
    except urllib.error.URLError as error:
        elapsed = time.monotonic() - attempt_started
        log(
            f"Gemini connection error: attempt={attempt} model={model} "
            f"elapsed_seconds={elapsed:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
        )
        log_exception("Gemini URLError", error)
        raise ApiError(
            504,
            f"Gemini connection error after {elapsed:.2f}s "
            f"(timeout={GEMINI_TIMEOUT_SECONDS}s): {error.reason!r}",
            retryable=True,
            overload=True,
            switch_provider=True,
        ) from error
    except TimeoutError as error:
        elapsed = time.monotonic() - attempt_started
        log(
            f"Gemini timeout: attempt={attempt} model={model} "
            f"elapsed_seconds={elapsed:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS} endpoint={endpoint}"
        )
        log_exception("Gemini TimeoutError", error)
        raise ApiError(
            504,
            f"Gemini timeout after {elapsed:.2f}s "
            f"(configured timeout={GEMINI_TIMEOUT_SECONDS}s): {error!r}",
            retryable=True,
            overload=True,
            switch_provider=True,
        ) from error
    except json.JSONDecodeError as error:
        log_exception("Gemini JSON decode error", error)
        log(f"Gemini invalid response body: {raw_response}")
        raise ApiError(
            502,
            f"Invalid Gemini JSON after {time.monotonic() - attempt_started:.2f}s: "
            f"{error}. Response: {raw_response}",
        ) from error


def call_chat_once(
    body: bytes, provider: str, attempt: int, overall_started: float
) -> dict:
    """Make one OpenAI-compatible /chat/completions request."""
    attempt_started = time.monotonic()
    label = PROVIDER_LABELS.get(provider, provider.title())
    base_url = provider_setting(provider, "base_url")
    model = provider_setting(provider, "model")
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider_key(provider)}",
    }
    if provider == PROVIDER_OPENROUTER:
        headers["HTTP-Referer"] = "https://bol-bindaas-project.onrender.com"
        headers["X-Title"] = "BolBindaas"

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    log(
        f"{label} attempt {attempt}/{MAX_ATTEMPTS}: provider={provider} "
        f"model={model} endpoint={endpoint} payload_bytes={len(body)} "
        f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )
    if DEBUG:
        log(f"{label} request payload: {body.decode('utf-8')}")

    raw_response = None
    response_status = None

    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            response_status = getattr(response, "status", None)
            raw_response = response.read().decode("utf-8", errors="replace")
            log(
                f"{label} response: attempt={attempt} status={response_status} "
                f"response_bytes={len(raw_response.encode('utf-8'))} "
                f"elapsed_seconds={time.monotonic() - attempt_started:.2f}"
            )
            log(f"{label} response body: {raw_response}")
            data = json.loads(raw_response)
            log_usage(data, provider)
            return data
    except urllib.error.HTTPError as error:
        raw_response = error.read().decode("utf-8", errors="replace")
        response_status = error.code
        headers_log = dict(error.headers.items()) if error.headers else {}
        log(
            f"{label} HTTP error: attempt={attempt} status={response_status} "
            f"reason={error.reason!r} "
            f"elapsed_seconds={time.monotonic() - attempt_started:.2f} "
            f"headers={headers_log}"
        )
        log(f"{label} error body: {raw_response}")
        log_exception(f"{label} HTTPError", error)
        detail = error_message_from_body(raw_response)
        temporary = response_status in TEMPORARY_STATUS_CODES
        browser_status = 503 if response_status in (429, 503) else 502
        raise ApiError(
            browser_status,
            f"{label} HTTP {response_status}: {detail}",
            retryable=response_status in RETRYABLE_STATUS_CODES,
            overload=temporary,
            headers=headers_log,
            switch_provider=temporary,
        ) from error
    except urllib.error.URLError as error:
        elapsed = time.monotonic() - attempt_started
        log(
            f"{label} connection error: attempt={attempt} "
            f"elapsed_seconds={elapsed:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
        )
        log_exception(f"{label} URLError", error)
        raise ApiError(
            504,
            f"{label} connection error after {elapsed:.2f}s "
            f"(timeout={GEMINI_TIMEOUT_SECONDS}s): {error.reason!r}",
            retryable=True,
            overload=True,
            switch_provider=True,
        ) from error
    except TimeoutError as error:
        elapsed = time.monotonic() - attempt_started
        log(
            f"{label} timeout: attempt={attempt} elapsed_seconds={elapsed:.2f} "
            f"timeout_seconds={GEMINI_TIMEOUT_SECONDS} endpoint={endpoint}"
        )
        log_exception(f"{label} TimeoutError", error)
        raise ApiError(
            504,
            f"{label} timeout after {elapsed:.2f}s "
            f"(configured timeout={GEMINI_TIMEOUT_SECONDS}s): {error!r}",
            retryable=True,
            overload=True,
            switch_provider=True,
        ) from error
    except json.JSONDecodeError as error:
        log_exception(f"{label} JSON decode error", error)
        log(f"{label} invalid response body: {raw_response}")
        raise ApiError(
            502,
            f"Invalid {label} JSON after {time.monotonic() - attempt_started:.2f}s: "
            f"{error}. Response: {raw_response}",
        ) from error


def extract_content(data: dict, model: str, overall_started: float) -> str:
    """Validate a successful Gemini response and return the English text."""
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
        f"Gemini success: model={model} "
        f"elapsed_seconds={time.monotonic() - overall_started:.2f} "
        f"output_chars={len(content.strip())}"
    )
    return content.strip()


def extract_chat_content(data: dict, provider: str, overall_started: float) -> str:
    """Validate an OpenAI-compatible response and return the English text."""
    label = PROVIDER_LABELS.get(provider, provider.title())
    full_response = json.dumps(data, ensure_ascii=False)

    if not isinstance(data, dict):
        log(f"{label} unexpected response shape: {full_response}")
        raise ApiError(502, f"Unexpected {label} response shape: {full_response}")

    try:
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") or ""
    except (IndexError, AttributeError, TypeError) as error:
        log_exception(f"{label} response parse error", error)
        log(f"{label} unexpected response shape: {full_response}")
        raise ApiError(502, f"Unexpected {label} response shape: {full_response}") from error

    if not content.strip():
        log(f"{label} empty result: {full_response}")
        raise ApiError(502, f"{label} returned an empty result. Full response: {full_response}")

    log(
        f"{label} success: provider={provider} model={provider_setting(provider, 'model')} "
        f"elapsed_seconds={time.monotonic() - overall_started:.2f} "
        f"output_chars={len(content.strip())}"
    )
    return content.strip()


def build_payload(provider: str, text: str, tone: str) -> dict:
    """Build the same translation instruction in each provider's format."""
    # The tone is an instruction layered on top of the fixed system prompt.
    user_content = text if tone == "normal" else f"Tone: {tone}\n\nText: {text}"

    if provider == PROVIDER_GEMINI:
        return {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
        }

    return {
        "model": provider_setting(provider, "model"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
    }


def call_provider(
    provider: str, text: str, tone: str, timings: dict, switch_early: bool = False
) -> str:
    """Call one provider with retries; temporary errors can trigger a switch."""
    overall_started = time.monotonic()
    label = PROVIDER_LABELS.get(provider, provider.title())
    model = model_for_attempt(1) if provider == PROVIDER_GEMINI else provider_setting(
        provider, "model"
    )
    body = json.dumps(
        build_payload(provider, text, tone), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    log(
        f"Provider request: provider={provider} model={model} "
        f"payload_bytes={len(body)} timeout_seconds={GEMINI_TIMEOUT_SECONDS}"
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if provider == PROVIDER_GEMINI:
                current_model = model_for_attempt(attempt)
                data = call_gemini_once(body, current_model, attempt, overall_started)
                result = extract_content(data, current_model, overall_started)
            else:
                data = call_chat_once(body, provider, attempt, overall_started)
                result = extract_chat_content(data, provider, overall_started)

            timings[f"{provider}_ms"] = round((time.monotonic() - overall_started) * 1000)
            return result
        except ApiError as error:
            log(
                f"{label} attempt failed: attempt={attempt}/{MAX_ATTEMPTS} "
                f"provider={provider} status={error.status} "
                f"retryable={error.retryable} overloaded={error.overload} "
                f"switchable={error.switch_provider} "
                f"elapsed_seconds={time.monotonic() - overall_started:.2f} "
                f"reason={error.message}"
            )

            # In Auto mode with another key available, switch on the first
            # temporary failure instead of spending the whole retry budget here.
            if (
                not error.retryable
                or attempt >= MAX_ATTEMPTS
                or (switch_early and error.switch_provider)
            ):
                timings[f"{provider}_ms"] = round(
                    (time.monotonic() - overall_started) * 1000
                )
                final_error = friendly_error(error, provider)
                log(
                    f"{label} final error: status={final_error.status} "
                    f"attempts={attempt} switch_provider={final_error.switch_provider} "
                    f"message={final_error.message}"
                )
                raise final_error from error

            delay = retry_delay(attempt, error.headers)
            if provider == PROVIDER_GEMINI:
                next_model = model_for_attempt(attempt + 1)
                log(
                    f"Gemini retry scheduled: next_attempt={attempt + 1}/{MAX_ATTEMPTS} "
                    f"model={next_model} fallback={next_model != current_model} "
                    f"delay_seconds={delay} backoff=exponential"
                )
            else:
                log(
                    f"{label} retry scheduled: next_attempt={attempt + 1}/{MAX_ATTEMPTS} "
                    f"provider={provider} delay_seconds={delay} backoff=exponential"
                )
            time.sleep(delay)

    raise ApiError(503, f"{label} is busy right now. Please try again in a moment.")


def call_ai(
    text: str, tone: str, timings: dict | None = None, provider: str | None = None
) -> str:
    """Translate with retries and automatic provider fallback."""
    overall_started = time.monotonic()
    timings = timings if timings is not None else {}

    requested = normalize_provider(
        provider if provider is not None else CONFIG.get("provider", PROVIDER_AUTO)
    )
    chain = provider_chain(requested)
    log(
        f"Provider chain: requested={requested} "
        f"chain={','.join(chain)} configured={','.join(configured_providers()) or 'none'}"
    )

    available = [name for name in chain if provider_key(name)]
    if not available:
        if requested in (PROVIDER_AUTO, PROVIDER_GEMINI):
            message = (
                "Gemini API key is not configured. Add AI_API_KEY to .env and restart "
                "the server (or set it in the hosting platform)."
            )
        else:
            env = PROVIDER_DEFAULTS[requested]["key_env"]
            message = (
                f"{PROVIDER_LABELS[requested]} API key is not configured. "
                f"Add {env} to .env and restart the server."
            )
        log(f"Provider error: {message}")
        raise ApiError(503, message)

    last_error = None
    for index, name in enumerate(available):
        # Switch immediately on temporary errors if a later provider has a key.
        switch_early = any(provider_key(item) for item in available[index + 1 :])
        try:
            result = call_provider(name, text, tone, timings, switch_early=switch_early)
        except ApiError as error:
            last_error = error
            log(
                f"Provider failed: provider={name} status={error.status} "
                f"switch_provider={error.switch_provider} "
                f"elapsed_seconds={time.monotonic() - overall_started:.2f}"
            )
            if error.switch_provider and switch_early:
                next_name = next(
                    (item for item in available[index + 1 :] if provider_key(item)), None
                )
                if next_name:
                    log(
                        f"Provider switch: {PROVIDER_LABELS[name]} failed "
                        f"(status={error.status}) -> trying {PROVIDER_LABELS[next_name]}"
                    )
                    continue
            raise

        timings["provider"] = name
        timings["total_ms"] = round((time.monotonic() - overall_started) * 1000)
        log(
            f"Provider success: provider={name} label={PROVIDER_LABELS[name]} "
            f"total_ms={timings['total_ms']} output_chars={len(result)}"
        )
        return result

    if last_error is None:
        last_error = ApiError(503, "No AI provider is available. Please try again.")
    raise last_error


class AppHandler(SimpleHTTPRequestHandler):
    """Serve static files, plus /api/health and POST /api/convert."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            selection = CONFIG.get("provider", PROVIDER_AUTO)
            self.send_json(
                200,
                {
                    "status": "ok",
                    "configured": bool(configured_providers()),
                    "provider": (
                        selection
                        if selection != PROVIDER_AUTO
                        else PROVIDER_GEMINI
                    ),
                    "provider_selection": selection,
                    "providers": configured_providers(),
                    "model": CONFIG["model"],
                    "fallback_model": CONFIG.get("fallback_model") or None,
                    "attempts": MAX_ATTEMPTS,
                },
            )
            return
        super().do_GET()

    def do_POST(self):
        self.request_started = time.monotonic()
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
        requested_provider = normalize_provider(payload.get("provider", PROVIDER_AUTO))

        if not isinstance(text, str) or not text.strip():
            self.send_json(400, {"error": "Please enter some Hinglish text."})
            return
        if len(text) > MAX_CHARS:
            self.send_json(400, {"error": f"Please keep your text under {MAX_CHARS} characters."})
            return
        if tone not in ALLOWED_TONES:
            self.send_json(400, {"error": "Unknown tone selection."})
            return

        timings = {}
        try:
            result = call_ai(text.strip(), tone, timings, provider=requested_provider)
        except ApiError as error:
            log(
                f"/api/convert failed: status={error.status} "
                f"total_ms={self.elapsed_ms()} message={error.message}"
            )
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

        provider = timings.get("provider", PROVIDER_GEMINI)
        log(
            f"/api/convert completed: status=200 total_ms={self.elapsed_ms()} "
            f"provider={provider} gemini_ms={timings.get('gemini_ms', '?')} "
            f"output_chars={len(result)}"
        )
        self.send_json(200, {"text": result, "provider": provider})

    def elapsed_ms(self) -> int:
        started = getattr(self, "request_started", None)
        return round((time.monotonic() - started) * 1000) if started else 0

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Server-Timing", f"app;dur={self.elapsed_ms()}")
        self.send_header("X-Response-Time-Ms", str(self.elapsed_ms()))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    configure()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5500"))

    log(f"Serving {ROOT} at http://{host}:{port}")
    log(f"AI provider selection: {CONFIG['provider']}")
    log(f"Configured providers: {', '.join(configured_providers()) or 'none'}")
    log(f"Gemini model: {CONFIG['model']}")
    ThreadingHTTPServer((host, port), AppHandler).serve_forever()


if __name__ == "__main__":
    main()
