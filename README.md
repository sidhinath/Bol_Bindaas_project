# BolBindaas - Bol bindaas, English hum sambhal lenge.

## Live Demo

🔗 https://bol-bindaas-project.onrender.com

## About

BolBindaas converts Hinglish (Hindi in Roman English) into clean, natural English. Type or speak your thought, choose a tone, and get an English version that keeps the original meaning and emotion.

## Features

- Hinglish text input with character count
- Voice input via Web Speech API (`hi-IN`)
- AI conversion through a server-side API call
- Gemini + Groq fallback: Gemini is primary; Groq takes over automatically on rate limits, high demand, timeouts, or network errors
- Automatic retries with exponential backoff; OpenAI and OpenRouter are available as optional extra backups
- Provider selection dropdown: Auto (recommended), Gemini, Groq, OpenAI, OpenRouter
- Response badge shows “Powered by Gemini” or “Powered by Groq” so you know who answered
- Quick tone pills: Casual, Professional, Polite, Direct (default), Empathetic
- Unified split-pane editor with 1px divider, live character count, voice input, and per-pane clear controls
- Loading skeleton and “Powered by …” attribution in the output pane
- Copy output to clipboard
- Listen to output with text-to-speech (`en-US`)
- Clear / New reset
- Loading feedback with elapsed time, empty-input, offline, and API error handling
- Responsive UI with light/dark theme

## How it works

1. User types or speaks in Hinglish, picks a tone pill and provider, then converts.
2. Browser sends `POST /api/convert` with the text, tone, and provider choice.
3. `server.py` tries Gemini first. On 429, 503, timeout, or network error it switches to Groq (then any optional extra backups).
4. The response returns `{ "text": "...", "provider": "gemini" }`; the UI shows the English output and a “Powered by Gemini” / “Powered by Groq” badge.
5. Copy, Listen, and Clear actions work the same regardless of provider.

## Interface

The app is a focused AI writing workspace with a compact header and a wide (up to 1180px) split-pane editor. The left pane holds the Hinglish textarea, tone pills, live `0 / 4000` counter, Speak button, and a quick Clear icon. The right pane shows the English output, a subtle loading skeleton while generating, the provider badge, and Copy / Listen / Clear / New actions. Input and output text use Inter at 18px with relaxed line height; labels and buttons stay at 14px or larger. On mobile the panes stack with a horizontal divider. Light and dark themes use the same deep-slate/indigo visual language.

## Tech stack

| Layer | Used |
| --- | --- |
| Frontend | HTML5, CSS3, vanilla JavaScript |
| Browser APIs | Web Speech API, SpeechSynthesis, Clipboard API, localStorage |
| Backend | Python 3 standard library (`http.server`, `urllib.request`) |
| AI | Gemini `generateContent` primary + Groq fallback; OpenAI/OpenRouter optional. Gemini → Groq Auto chain, 3 attempts, exponential backoff |
| Dependencies | None |
| Testing | Python `unittest` + Node built-in test runner |

## Project structure

```text
Bol_Bindaas_project/
├── index.html        # UI markup
├── style.css         # Styling and themes
├── app.js            # Frontend logic
├── server.py         # Static server and /api/convert
├── .env.example      # Environment variable template
├── package.json      # Project metadata and npm scripts
├── requirements.txt  # No third-party packages
├── tests/            # Automated backend and frontend tests
└── .gitignore        # Ignores .env and caches
```

## Prerequisites

- Python 3.10+
- Node.js 18+ (optional, for `npm start`)
- Chrome recommended for voice input
- Gemini API key (https://aistudio.google.com/apikey) and optionally a Groq key (https://console.groq.com/keys) for fallback
- Internet access

## Setup

```bash
git clone https://github.com/sidhinath/Bol_Bindaas_project.git
cd Bol_Bindaas_project
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Add your keys to `.env`:

```env
# auto | gemini | groq | openai | openrouter
AI_PROVIDER=auto

# Primary provider (AI_API_KEY / GOOGLE_API_KEY also work)
GEMINI_API_KEY=AIza-your-gemini-key-here

# Fallback on 429 / 503 / timeout / network error
GROQ_API_KEY=gsk_your-groq-key-here

AI_MODEL=gemini-3.5-flash-lite
# GROQ_MODEL=llama-3.1-8b-instant
# AI_FALLBACK_MODEL=gemini-3.1-flash-lite  # lighter Gemini backup
# AI_MAX_ATTEMPTS=3                        # per provider, 1-5
# AI_TIMEOUT_SECONDS=30                    # 5-120
```

Gemini alone works; add `GROQ_API_KEY` to enable automatic fallback. OpenAI and OpenRouter keys are optional extra backups:

```env
# OPENAI_API_KEY=sk-your-openai-key-here     # https://platform.openai.com/api-keys
# OPENROUTER_API_KEY=sk-or-your-key-here     # https://openrouter.ai/keys
```

Optional per-provider overrides: `GROQ_MODEL` (default `llama-3.1-8b-instant`), `OPENAI_MODEL` (default `gpt-4o-mini`), `OPENROUTER_MODEL` (default `openai/gpt-4o-mini`), plus matching `<PROVIDER>_BASE_URL` values. See `.env.example` for the full template.

## Gemini + Groq fallback

| Setting | Behavior |
| --- | --- |
| `AI_PROVIDER=auto` | Gemini → Groq → OpenAI → OpenRouter, skipping providers without a key. Recommended. |
| `AI_PROVIDER=gemini` / `groq` / `openai` / `openrouter` | Uses only that provider. |
| Provider dropdown in the UI | Per-request override with the same five choices; sent as `provider` in the request body. |

- If Gemini returns **429**, **503**, times out, or has a network error, Auto mode switches to Groq immediately; other errors are returned with a clear message.
- Each provider still gets up to `AI_MAX_ATTEMPTS` requests with exponential backoff when no later provider is available.
- Groq uses an OpenAI-compatible `chat/completions` call with the exact same translation instruction, so quality and output format stay consistent.
- `POST /api/convert` returns `{ "text": "...", "provider": "groq" }` when Groq answers; the UI shows “Powered by Groq”.
- `GET /api/health` reports `provider_selection` and the list of configured `providers`.

Keys are never sent to the browser. Logs record the provider chain, attempts, switches, token usage, and response times.

## Run locally

```bash
python server.py
```

Or:

```bash
npm start
```

Open **http://127.0.0.1:5500/**. Health check: **/api/health**.

## Testing

The test suite uses only built-in tools, so there is nothing extra to install.

```bash
npm test
```

Run either part on its own:

```bash
npm run test:backend
npm run test:frontend
```

Generate coverage reports:

```bash
npm run test:coverage
```

Node prints frontend coverage to the terminal. Python writes a line-coverage report for `server.py` to `.coverage/server.py.cover`.

The backend tests mock Gemini and the OpenAI-compatible endpoints locally, so retries, provider switches, fallback, and overload responses are covered without any API key. Render logs include the provider chain, selected model, payload size, response status, elapsed time, token usage, and every retry or provider switch.

## Performance

- Uses the fastest supported translation model (`gemini-3.5-flash-lite`) and automatically upgrades slow legacy model values left in Render.
- In Auto mode, a temporary Gemini failure switches immediately to Groq instead of waiting through a full retry cycle.
- Sends a compact instruction with no filler and caps output at 1024 tokens; full payload logging is opt-in via `AI_DEBUG=1`.
- Logs `/api/convert` total time and Gemini time in milliseconds, and returns `Server-Timing` / `X-Response-Time-Ms` response headers.
- The button shows elapsed time while converting, and the output pane has an animated skeleton state.

## Deployment

Deploy as a Python web service on Render:

- Repository: https://github.com/sidhinath/Bol_Bindaas_project
- Build command: `pip install -r requirements.txt`
- Start command: `python server.py`
- Health check: `/api/health`
- Environment variables:
  - Provider selection: `AI_PROVIDER` (default `auto`; `gemini`, `groq`, `openai`, `openrouter` for a fixed provider)
  - Keys: `GEMINI_API_KEY` (or legacy `AI_API_KEY`/`GOOGLE_API_KEY`) and `GROQ_API_KEY` for fallback; `OPENAI_API_KEY` / `OPENROUTER_API_KEY` are optional extras
  - Gemini tuning: `AI_MODEL` (default `gemini-3.5-flash-lite`; older `gemini-3.8-flash`/`3.6-flash` values are auto-upgraded), `AI_ALLOW_LEGACY_MODEL=1` to keep them, `AI_FALLBACK_MODEL` (default `gemini-3.1-flash-lite`)
  - Optional overrides: `OPENAI_MODEL`, `GROQ_MODEL`, `OPENROUTER_MODEL`, `OPENAI_BASE_URL`, `GROQ_BASE_URL`, `OPENROUTER_BASE_URL`, `AI_BASE_URL`
  - Reliability: `AI_MAX_ATTEMPTS` (default `3`), `AI_TIMEOUT_SECONDS` (default `30`), `AI_DEBUG` (set `1` to include raw provider details in browser responses)
  - Platform: `HOST=0.0.0.0`, `PORT` (set by Render)

## Usage examples

| Hinglish input | Tone | English output |
| --- | --- | --- |
| `aaj mera mood thoda off hai` | Direct | Today I am feeling a little low. |
| `sir, main report aaj shaam tak bhej dunga` | Polite | Sir, I will send the report by this evening. |
| `yaar plan cancel ho gaya` | Casual | The plan got cancelled, man. |

## Limitations

- Voice input works best in Chrome.
- Accuracy depends on browser speech recognition and the AI model.
- AI conversion needs an API key and internet access.

## Author

Sidhi Nath — GitHub: [sidhinath](https://github.com/sidhinath), B.Tech CSE student.

## License

MIT
