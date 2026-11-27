# BolBindaas - Bol bindaas, English hum sambhal lenge.

## Live Demo

🔗 https://bol-bindaas-project.onrender.com

## About

BolBindaas converts Hinglish (Hindi in Roman English) into clean, natural English. Type or speak your thought, choose a tone, and get an English version that keeps the original meaning and emotion.

## Features

- Hinglish text input with character count
- Voice input via Web Speech API (`hi-IN`)
- AI conversion through a server-side API call
- Multi-provider fallback: Gemini first, then optional OpenAI, Groq, and OpenRouter
- Automatic retries with exponential backoff; temporary errors switch to the next configured provider
- Provider selection dropdown: Auto (recommended), Gemini, OpenAI, Groq, OpenRouter
- Response badge shows which provider actually generated the answer
- Tone selector: Normal, Formal, Casual, Poetic
- Copy output to clipboard
- Listen to output with text-to-speech (`en-US`)
- Clear / New reset
- Loading feedback with elapsed time, empty-input, offline, and API error handling
- Responsive UI with light/dark theme

## How it works

1. User types or speaks in Hinglish and picks a tone and provider.
2. Browser sends `POST /api/convert` with the text, tone, and provider choice.
3. `server.py` tries Gemini first. On a temporary failure (429, 503, timeout, or network error) it switches to the next configured provider, retrying with exponential backoff.
4. The response returns `{ "text": "...", "provider": "gemini" }`; the UI shows the English output and a “via Gemini” style badge.
5. Copy, Listen, and Clear actions work the same regardless of provider.

## Tech stack

| Layer | Used |
| --- | --- |
| Frontend | HTML5, CSS3, vanilla JavaScript |
| Browser APIs | Web Speech API, SpeechSynthesis, Clipboard API, localStorage |
| Backend | Python 3 standard library (`http.server`, `urllib.request`) |
| AI | Gemini `generateContent` + OpenAI-compatible providers (OpenAI / Groq / OpenRouter); Gemini-first Auto chain, 3 attempts, exponential backoff |
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
- At least one AI provider key (Gemini recommended: https://aistudio.google.com/apikey)
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

Add at least one provider key to `.env`. Gemini alone is enough to start:

```env
# auto | gemini | openai | groq | openrouter
AI_PROVIDER=auto

# Primary provider (AI_API_KEY / GOOGLE_API_KEY also work)
GEMINI_API_KEY=AIza-your-gemini-key-here

AI_MODEL=gemini-3.5-flash-lite
# AI_FALLBACK_MODEL=gemini-3.1-flash-lite  # lighter Gemini backup
# AI_MAX_ATTEMPTS=3                        # per provider, 1-5
# AI_TIMEOUT_SECONDS=30                    # 5-120
```

To enable automatic fallbacks, add any of these keys:

```env
OPENAI_API_KEY=sk-your-openai-key-here     # https://platform.openai.com/api-keys
GROQ_API_KEY=gsk_your-groq-key-here        # https://console.groq.com/keys
OPENROUTER_API_KEY=sk-or-your-key-here     # https://openrouter.ai/keys
```

Optional per-provider overrides: `OPENAI_MODEL` (default `gpt-4o-mini`), `GROQ_MODEL` (default `llama-3.1-8b-instant`), `OPENROUTER_MODEL` (default `openai/gpt-4o-mini`), plus matching `<PROVIDER>_BASE_URL` values. See `.env.example` for the full template.

## Multiple providers

| Setting | Behavior |
| --- | --- |
| `AI_PROVIDER=auto` | Tries Gemini → OpenAI → Groq → OpenRouter, skipping providers without a key. Recommended. |
| `AI_PROVIDER=gemini` / `openai` / `groq` / `openrouter` | Uses only that provider. |
| Provider dropdown in the UI | Per-request override with the same five choices; sent as `provider` in the request body. |

- A temporary failure (HTTP 429 or 503, timeout, or network error) switches to the next configured provider immediately in Auto mode; other errors are returned with a clear message.
- Each provider still gets up to `AI_MAX_ATTEMPTS` requests with exponential backoff when no later provider is available.
- All providers receive the same translation instruction, so the output format is identical.
- `POST /api/convert` returns the provider name in `provider`; the UI shows it as a badge beside “English version”.
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
- In Auto mode, a temporary Gemini failure switches immediately to a configured backup provider instead of waiting through a full retry cycle.
- Sends a compact instruction with no filler and caps output at 1024 tokens; full payload logging is opt-in via `AI_DEBUG=1`.
- Logs `/api/convert` total time and Gemini time in milliseconds, and returns `Server-Timing` / `X-Response-Time-Ms` response headers.
- The button shows elapsed time while converting, and the output panel has an animated loading indicator.

## Deployment

Deploy as a Python web service on Render:

- Repository: https://github.com/sidhinath/Bol_Bindaas_project
- Build command: `pip install -r requirements.txt`
- Start command: `python server.py`
- Health check: `/api/health`
- Environment variables:
  - Provider selection: `AI_PROVIDER` (default `auto`; `gemini`, `openai`, `groq`, `openrouter` for a fixed provider)
  - Keys: `GEMINI_API_KEY` (or legacy `AI_API_KEY`/`GOOGLE_API_KEY`), `OPENAI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` — set only the ones you need
  - Gemini tuning: `AI_MODEL` (default `gemini-3.5-flash-lite`; older `gemini-3.8-flash`/`3.6-flash` values are auto-upgraded), `AI_ALLOW_LEGACY_MODEL=1` to keep them, `AI_FALLBACK_MODEL` (default `gemini-3.1-flash-lite`)
  - Optional overrides: `OPENAI_MODEL`, `GROQ_MODEL`, `OPENROUTER_MODEL`, `OPENAI_BASE_URL`, `GROQ_BASE_URL`, `OPENROUTER_BASE_URL`, `AI_BASE_URL`
  - Reliability: `AI_MAX_ATTEMPTS` (default `3`), `AI_TIMEOUT_SECONDS` (default `30`), `AI_DEBUG` (set `1` to include raw provider details in browser responses)
  - Platform: `HOST=0.0.0.0`, `PORT` (set by Render)

## Usage examples

| Hinglish input | Tone | English output |
| --- | --- | --- |
| `aaj mera mood thoda off hai` | Normal | Today I am feeling a little low. |
| `sir, main report aaj shaam tak bhej dunga` | Formal | Sir, I will send the report by this evening. |
| `yaar plan cancel ho gaya` | Casual | The plan got cancelled, man. |

## Limitations

- Voice input works best in Chrome.
- Accuracy depends on browser speech recognition and the AI model.
- AI conversion needs an API key and internet access.

## Author

Sidhi Nath — GitHub: [sidhinath](https://github.com/sidhinath), B.Tech CSE student.

## License

MIT
