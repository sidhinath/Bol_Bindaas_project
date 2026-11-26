# BolBindaas - Bol bindaas, English hum sambhal lenge.

![BolBindaas Screenshot](./screenshot.png)

## About

People often think and speak in **Hinglish** — Hindi written in the English alphabet, mixed with English words — but need to share the same thought in clean English at work, in college, or in messages. BolBindaas solves that gap: you speak or type whatever is on your mind in Hinglish, and the app rewrites it into natural, well-written English while keeping the original meaning, emotion, and tone.

It is not a word-by-word dictionary translation. The AI is instructed to *write* the thought in English, so the result reads like something a person would actually write.

## Features

- **Hinglish text input** — a large textarea with a live character counter (4000 characters max).
- **Voice input** — Web Speech API with `lang = "hi-IN"`, live interim transcript in the textarea, "Listening..." indicator, and a friendly fallback message when unsupported.
- **AI conversion** — sends the text and selected tone to a server route that calls an OpenAI-compatible chat model with a fixed system prompt.
- **Tone selector** — `Normal`, `Formal`, `Casual`, and `Poetic`.
- **Copy** — copies the converted English to the clipboard and shows "Copied!".
- **Listen** — text-to-speech playback using `speechSynthesis` with `en-US`.
- **Clear / New** — resets input, output, speech state, and buttons.
- **Loading and error handling** — busy states, empty-input checks, offline detection, and readable API errors.
- **Dark/light theme** — follows the OS preference and includes a manual toggle saved in `localStorage`.
- **Responsive UI** — two-panel layout on desktop, stacked panels on mobile.

## How it works

1. **Input** — the user types in the textarea or clicks **Speak**. Speech recognition (`hi-IN`) fills the textarea live while the user talks.
2. **Request** — clicking **Convert to English** sends `POST /api/convert` with `{ "text": "...", "tone": "normal" }`. The browser never sees the API key.
3. **AI call** — `server.py` reads `AI_API_KEY` from the environment, adds the fixed system prompt, and calls an OpenAI-compatible `/chat/completions` endpoint.
4. **Output** — the English text is returned as `{ "text": "..." }`, shown in the output card, and made available for **Copy**, **Listen**, and **Clear / New**.

## Tech stack

| Layer | What is actually used |
| --- | --- |
| Frontend | HTML5, CSS3, vanilla JavaScript (ES6+) |
| Browser APIs | Web Speech API (`SpeechRecognition`, `hi-IN`), `speechSynthesis` (`en-US`), Clipboard API, `localStorage`, `fetch` |
| Backend | Python 3 standard library only: `http.server`, `urllib.request`, `json`, `os`, `pathlib` |
| AI API | OpenAI-compatible Chat Completions API (`POST /chat/completions`) |
| Config | `.env` parsed by a small custom loader in `server.py` |
| Package metadata | `package.json` (name/scripts/repo links only; no npm dependencies) |
| Dependencies | **None** — `requirements.txt` is intentionally comment-only |

## Project structure

```text
Bol_Bindaas_project/
├── index.html        # Page structure: input panel, tone selector, output card, actions
├── style.css         # Responsive layout, dark/light theme tokens, animations
├── app.js            # Frontend logic: conversion, voice input, copy, listen, theme
├── server.py         # Static file server + /api/health + POST /api/convert AI proxy
├── .env.example      # Template for API key and model settings
├── .env              # Local secrets (not committed)
├── package.json      # Project name, npm scripts, GitHub repository metadata
├── requirements.txt  # Comment-only; no third-party Python packages
├── .gitignore        # Ignores .env, caches, and local environments
└── README.md         # This file
```

> Add your own image at `./screenshot.png` to replace the placeholder above.

## Prerequisites

- **Python 3.10+** (tested with Python 3.13). No third-party Python packages are needed.
- **Node.js 18+** — optional; only used for the `npm start` / `npm run dev` scripts in `package.json`.
- **Browser** — Chrome is recommended, especially for voice input. Microsoft Edge also supports the Web Speech API.
- **Microphone permission** and `localhost` or HTTPS for voice/clipboard features.
- **API key** for an OpenAI-compatible chat endpoint (for example, an OpenAI API key).
- Internet access for AI conversion and browser speech services.

## Installation and setup

```bash
git clone https://github.com/sidhinath/Bol_Bindaas_project.git
cd Bol_Bindaas_project
```

Create the environment file from the template:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Add your key to `.env`:

```env
AI_API_KEY=sk-your-real-key-here
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```

Install dependencies — there are no runtime dependencies, but these commands are safe:

```bash
pip install -r requirements.txt
npm install
```

> `npm install` only reads the metadata in `package.json`; it does not add any libraries used by the app.

## Running locally

Start the Python server:

```bash
python server.py
```

Or use the npm script:

```bash
npm start
```

Then open:

- App: **http://127.0.0.1:5500/**
- Health check: **http://127.0.0.1:5500/api/health**

The health endpoint reports `"configured": true` once `AI_API_KEY` is loaded.

## Deployment

This app is deployed as a **Python web service** (Render is the recommended platform). It is not deployed on Vercel or Netlify as-is: those platforms would require rewriting `server.py` as a serverless function.

### Deploy on Render

1. Push the code to **https://github.com/sidhinath/Bol_Bindaas_project** without committing `.env`.
2. In Render, create a **New Web Service** and connect that repository.
3. Set:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt` (or leave blank)
   - **Start Command:** `python server.py`
   - **Health Check Path:** `/api/health`
4. Add environment variables:

   | Variable | Required | Value / purpose |
   | --- | --- | --- |
   | `AI_API_KEY` | Yes | Your AI provider key |
   | `AI_BASE_URL` | No | Defaults to `https://api.openai.com/v1` |
   | `AI_MODEL` | No | Defaults to `gpt-4o-mini` |
   | `HOST` | Yes for Render | `0.0.0.0` |
   | `PORT` | Auto | Provided by Render; the app reads it |

5. Deploy. The same service serves both the frontend and `/api/convert`, so no CORS configuration is needed.

## Usage examples

| Hinglish input | Tone | English output |
| --- | --- | --- |
| `aaj mera mood thoda off hai, kuch samajh nahi aa raha kya karun` | Normal | Today I'm feeling a little low, and I'm not sure what to do next. |
| `sir, main aapko report aaj shaam tak bhej dunga` | Formal | Sir, I will send you the report by this evening. |
| `yaar kal ka plan cancel kar diya, ab kya karein?` | Casual | I cancelled tomorrow's plan, man. What should we do now? |

> Outputs are generated by the AI model, so exact wording can vary each time.

## Limitations

- Voice input works best in **Chrome**; other browsers may hide the mic button or give poorer recognition.
- Speech accuracy depends on the browser's speech service, microphone quality, accents, and internet connection.
- Conversion accuracy depends on the selected AI model; the app does not guarantee a perfect result.
- AI conversion requires an API key and internet access.
- Clipboard access and text-to-speech can be restricted by some browsers or insecure origins.
- Input is capped at **4000 characters** in both the UI and the backend.

## Future improvements

- Support for more Indian languages and mixed-language inputs.
- Conversion history saved locally or per user.
- Download the English output as `.txt` or PDF.
- Better punctuation and formatting control.
- Custom vocabulary for names, places, and technical terms.
- Rate limiting and optional user authentication for public deployments.

## Author

**Sidhi Nath** — GitHub: [sidhinath](https://github.com/sidhinath)  
B.Tech CSE student.

## License

MIT
