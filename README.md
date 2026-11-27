# BolBindaas — Say it in Hinglish. Write it in English.

BolBindaas turns Hinglish thoughts into clean, natural English. Type or speak in Roman Hindi, choose a tone, and get a polished English version that keeps the original meaning and emotion.

## Live Links

- **Live Web App:** https://bol-bindaas-project.onrender.com (hosted on https://onrender.com)
- **Download Android App (APK):** https://github.com/sidhinath/Bol_Bindaas_project/releases/latest

## Project Overview

BolBindaas is a focused, single-purpose writing workspace: no accounts, no dashboards, no clutter. The same frontend runs in the browser and inside a native Android WebView. The browser sends each conversion to a small Python server, which holds the AI keys and calls the configured providers.

The web deployment stays on Render; the Android build uses Capacitor and calls that same deployed API.

## Key UI & Feature Highlights

- **Modern responsive UI:** Desktop shows a centered split-pane editor with input and output side by side. Mobile (`≤820px`) stacks the panes into a natural flow: **Your thought → Speak → Convert to English → English version → Copy / Listen / Clear / New**.
- **One-click Tone pills:** Casual, Professional, Polite, **Direct** (default), and Empathetic. The active pill uses the indigo-to-violet gradient.
- **Dark / Light mode toggle:** A header button switches themes and remembers the choice in `localStorage`.
- **Voice Input & Text-to-Speech:** **Speak** uses the Web Speech API with Hindi (`hi-IN`) recognition; **Listen** reads the English result with SpeechSynthesis (`en-US`).
- **Multi-provider AI fallback:** In Auto mode, Gemini runs first; Groq takes over on rate limits, high demand, timeouts, or network errors. Optional OpenAI and OpenRouter keys add further backups. The dropdown also allows a fixed `auto`, `gemini`, `openai`, `groq`, or `openrouter` choice.
- **Native Android app support via Capacitor:** The `www/` web assets and `android/` project are ready to open in Android Studio. In the native runtime, `app.js` calls the deployed Render API.
- **Focused conversion workflow:** 4,000-character input with a live counter, loading skeleton, elapsed-time feedback, empty/offline/API error handling, and `Ctrl/Cmd + Enter` shortcut.
- **Clean output actions:** Copy, Listen, and **Clear / New**. The API still returns the responding provider; the legacy `#providerBadge` element stays in the DOM for `app.js` but is visually hidden.

## Tech Stack & Architecture

| Layer | Used |
| --- | --- |
| Frontend | Vanilla HTML/CSS/JavaScript — one self-contained `index.html` with embedded CSS and `app.js` |
| UI style | Flexbox/Grid, Inter-first system font stack, dark/light theme tokens |
| Browser APIs | Web Speech API, SpeechSynthesis, Clipboard API, `localStorage` |
| Backend | `server.py` — Python 3 standard library only (`http.server`, `urllib.request`, `json`, `os`) with CORS headers and `OPTIONS /api/convert` preflight support |
| Mobile | Capacitor — `capacitor.config.json`, `www/`, and an `android/` Android Studio project |
| Testing | Python `unittest` and the Node.js built-in test runner |

```text
Web browser / Capacitor Android WebView
  │
  │  POST /api/convert  { "text": "...", "tone": "direct", "provider": "auto" }
  ▼
server.py
  • serves the web app on Render
  • validates input and tone
  • reads API keys from .env or the real environment
  • sends CORS headers for cross-origin Android requests
  • keeps every key server-side
  ▼
Gemini  →  Groq  →  OpenAI  →  OpenRouter
(primary)  (automatic fallback)  (optional backups)
  ▼
{ "text": "Clean natural English", "provider": "gemini" }
```

`GET /api/health` reports status, provider selection, configured providers, and model settings. All active styling lives in `index.html`; `style.css` remains only as an unused legacy file.

## Setup & Running Locally

### Prerequisites

- Python 3.10+
- A Gemini API key: https://aistudio.google.com/apikey
- Optional keys for Groq, OpenAI, and OpenRouter
- Node.js 18+ for the `npm` scripts, tests, and Capacitor sync
- Chrome recommended for voice input

### Run the web app

```bash
git clone https://github.com/sidhinath/Bol_Bindaas_project.git
cd Bol_Bindaas_project
cp .env.example .env          # Windows: Copy-Item .env.example .env
```

Add at least the primary key to `.env`:

```env
AI_PROVIDER=auto
GEMINI_API_KEY=your-gemini-key-here
GROQ_API_KEY=your-groq-key-here   # recommended fallback
```

Optional extra backups: `OPENAI_API_KEY` and `OPENROUTER_API_KEY`.

```bash
python server.py
```

Open **http://127.0.0.1:5500/**. Health check: **http://127.0.0.1:5500/api/health**.

### Build the Android app

```bash
npm run sync:android    # copies index.html + app.js into www/, then runs cap sync
```

Open the `android/` folder in Android Studio and run it on a device or emulator. Download the published APK from the [Releases page](https://github.com/sidhinath/Bol_Bindaas_project/releases/latest).

## API

**POST /api/convert**

```json
{
  "text": "aaj mera mood thoda off hai",
  "tone": "direct",
  "provider": "auto"
}
```

```json
{
  "text": "Today I am feeling a little low.",
  "provider": "gemini"
}
```

Tones: `casual`, `professional`, `polite`, `direct`, `empathetic`. Providers: `auto`, `gemini`, `openai`, `groq`, `openrouter`. Invalid JSON, empty or oversized text, and unknown tones are rejected before any provider is called.

## Testing

```bash
npm test
```

Individual suites: `npm run test:backend` and `npm run test:frontend`. Coverage: `npm run test:coverage`. Backend tests mock provider endpoints, so no real API key is needed.

## Deployment

Deploy as a Python web service:

- **Build command:** `pip install -r requirements.txt` (no third-party packages)
- **Start command:** `python server.py`
- **Health check:** `/api/health`
- **Environment:** `HOST`, `PORT`, `AI_PROVIDER`, and the provider keys described above

## Project Structure

```text
Bol_Bindaas_project/
├── index.html          # Self-contained UI markup and inline CSS
├── app.js              # Vanilla JS for tones, theme, voice, conversion, output
├── server.py           # Static server, health/convert routes, CORS, fallback
├── www/                # Capacitor web assets copied from index.html + app.js
├── android/            # Capacitor Android project for Android Studio
├── capacitor.config.json
├── .env.example        # Environment variable template
├── package.json        # npm scripts for run, sync, and tests
├── requirements.txt    # Empty: standard library only
├── tests/              # Python unittest + Node test runner suites
└── .gitignore          # Ignores .env, caches, node_modules, build artifacts
```

## Limitations

- Voice input depends on browser speech recognition and works best in Chrome.
- AI conversion needs an API key and an internet connection.
- Output quality follows the selected provider and model.

## License

MIT

## Author / Developer

Developed by **Sidhinath Kumar** — [GitHub](https://github.com/sidhinath).
