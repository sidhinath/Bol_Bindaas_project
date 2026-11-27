# BolBindaas — Say it in Hinglish. Write it in English.

BolBindaas turns Hinglish thoughts into clean, natural English. Type or speak in Roman Hindi, choose a tone, and get a polished English version that keeps the original meaning and emotion.

**Live demo:** https://bol-bindaas-project.onrender.com  
**Health check:** https://bol-bindaas-project.onrender.com/api/health  
**Download Android App (APK):** https://github.com/sidhinath/Bol_Bindaas_project/releases

## Project Overview

BolBindaas is a focused, single-purpose writing workspace: no accounts, no dashboards, no clutter. The browser sends each conversion to a small Python server, which holds the AI keys and calls the configured providers. The page itself is self-contained, responsive, and framework-free.

The app is designed to feel quick and calm: a centered workspace, two clear panes, one prominent **Convert to English** action, and simple Copy / Listen / Clear controls after every result.

## Key UI & Feature Highlights

- **Modern responsive split-pane editor:** On desktop, the input and output panes sit side by side with a subtle divider. On screens `≤820px`, they stack into a mobile flow: **Your thought → Speak → Convert to English → English version → Copy / Listen / Clear / New**.
- **One-click tone pills:** Casual, Professional, Polite, **Direct** (default), and Empathetic. The active pill uses the same indigo-to-violet gradient as the primary button.
- **Dark / Light theme toggle:** A header button switches themes and remembers the choice in `localStorage`.
- **Voice input and playback:** **Speak** uses the Web Speech API with Hindi (`hi-IN`) recognition; **Listen** reads the English result with SpeechSynthesis (`en-US`). Unsupported browsers get a clear fallback message.
- **Multi-provider AI support:** In Auto mode, Gemini runs first; Groq takes over on rate limits, high demand, timeouts, or network errors. Optional OpenAI and OpenRouter keys add further backups. A header dropdown also allows a fixed `auto`, `gemini`, `openai`, `groq`, or `openrouter` choice.
- **Focused conversion workflow:** 4,000-character input with a live counter, loading skeleton, elapsed-time feedback, empty/offline/API error handling, and keyboard shortcut `Ctrl/Cmd + Enter`.
- **Clean output actions:** Copy to clipboard, listen to the result, or reset both panes with **Clear / New**. The API still returns the responding provider; the legacy `#providerBadge` element is kept in the DOM for `app.js` but visually hidden with CSS so the output header stays clean.

## Tech Stack & Architecture

| Layer | Used |
| --- | --- |
| Frontend | One self-contained `index.html` with embedded CSS, Flexbox/Grid layout, and vanilla JavaScript in `app.js` |
| UI style | Inter-first system font stack; dark/light theme tokens; no external fonts, icons, or CSS files |
| Browser APIs | Web Speech API, SpeechSynthesis, Clipboard API, `localStorage` |
| Backend | `server.py` — Python 3 standard library only (`http.server`, `urllib.request`, `json`, `os`) |
| Dependencies | None on either side; no frontend framework, bundler, SDK, or Python package install needed |
| Testing | Python `unittest` and the Node.js built-in test runner |

```text
Browser (index.html + app.js)
  │
  │  POST /api/convert  { "text": "...", "tone": "direct", "provider": "auto" }
  ▼
server.py
  • serves the static page
  • validates input and tone
  • reads API keys from .env or the real environment
  • keeps every key server-side
  ▼
Gemini  →  Groq  →  OpenAI  →  OpenRouter
(primary)  (automatic fallback)  (optional backups)
  ▼
{ "text": "Clean natural English", "provider": "gemini" }
```

`GET /api/health` reports status, provider selection, configured providers, and model settings. All active styling lives in `index.html`; `style.css` remains in the repository only as an unused legacy file.

## Setup & Running Locally

### 1. Prerequisites

- Python 3.10+
- A Gemini API key: https://aistudio.google.com/apikey
- Optional keys for Groq, OpenAI, and OpenRouter
- Chrome recommended for voice input
- Node.js 18+ only if you want the `npm` scripts or tests

### 2. Get the code

```bash
git clone https://github.com/sidhinath/Bol_Bindaas_project.git
cd Bol_Bindaas_project
```

Create your local environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### 3. Add keys to `.env`

At minimum, set the primary Gemini key:

```env
AI_PROVIDER=auto
GEMINI_API_KEY=your-gemini-key-here
```

Recommended fallback:

```env
GROQ_API_KEY=your-groq-key-here
```

Optional extra backups:

```env
OPENAI_API_KEY=your-openai-key-here
OPENROUTER_API_KEY=your-openrouter-key-here
```

`server.py` reads `.env` directly with the standard library; no `python-dotenv` install is needed. Real environment variables take precedence over `.env` values. See `.env.example` for optional model, base URL, retry, timeout, and host/port settings.

### 4. Start the server

```bash
python server.py
```

Or, if you have Node.js installed:

```bash
npm start
```

Open **http://127.0.0.1:5500/**. Check **http://127.0.0.1:5500/api/health**. Press `Ctrl + C` in the terminal to stop the server.

## API

**Request**

```http
POST /api/convert
Content-Type: application/json
```

```json
{
  "text": "aaj mera mood thoda off hai",
  "tone": "direct",
  "provider": "auto"
}
```

**Response**

```json
{
  "text": "Today I am feeling a little low.",
  "provider": "gemini"
}
```

Tones are `casual`, `professional`, `polite`, `direct`, and `empathetic`. Providers are `auto`, `gemini`, `openai`, `groq`, and `openrouter`. Invalid JSON, empty or oversized text, and unknown tones are rejected before any provider is called.

## Testing

The suite uses only built-in tools.

```bash
npm test
```

Run either part separately:

```bash
npm run test:backend
npm run test:frontend
```

Generate coverage reports:

```bash
npm run test:coverage
```

Backend tests mock the provider endpoints locally, so fallback and retry behavior is covered without real API keys.

## Deployment

Deploy as a Python web service with:

- **Build command:** `pip install -r requirements.txt` (no third-party packages)
- **Start command:** `python server.py`
- **Health check:** `/api/health`
- **Environment:** set `HOST`, `PORT`, `AI_PROVIDER`, and the provider keys described above

## Project Structure

```text
Bol_Bindaas_project/
├── index.html        # Self-contained UI markup and inline CSS
├── app.js            # Vanilla JS: tones, theme, voice, conversion, output actions
├── server.py         # Static server, /api/health, /api/convert, provider fallback
├── .env.example      # Environment variable template
├── package.json      # npm scripts for running and testing
├── requirements.txt  # Empty: standard library only
├── tests/            # Python unittest + Node test runner suites
└── .gitignore        # Ignores .env, caches, and coverage output
```

## Limitations

- Voice input depends on browser speech recognition and works best in Chrome.
- AI conversion needs an API key and an internet connection.
- Output quality follows the selected provider and model.

## Author

Sidhi Nath — GitHub: [sidhinath](https://github.com/sidhinath), B.Tech CSE student.

## License

MIT
