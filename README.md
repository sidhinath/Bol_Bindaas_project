# BolBindaas - Bol bindaas, English hum sambhal lenge.

## About

BolBindaas converts Hinglish (Hindi in Roman English) into clean, natural English. Type or speak your thought, choose a tone, and get an English version that keeps the original meaning and emotion.

## Features

- Hinglish text input with character count
- Voice input via Web Speech API (`hi-IN`)
- AI conversion through a server-side API call
- Tone selector: Normal, Formal, Casual, Poetic
- Copy output to clipboard
- Listen to output with text-to-speech (`en-US`)
- Clear / New reset
- Loading, empty-input, offline, and API error handling
- Responsive UI with light/dark theme

## How it works

1. User types or speaks in Hinglish.
2. Browser sends `POST /api/convert` with the text and tone.
3. `server.py` calls an OpenAI-compatible chat API using the key from `.env`.
4. The English output is shown with Copy, Listen, and Clear actions.

## Tech stack

| Layer | Used |
| --- | --- |
| Frontend | HTML5, CSS3, vanilla JavaScript |
| Browser APIs | Web Speech API, SpeechSynthesis, Clipboard API, localStorage |
| Backend | Python 3 standard library (`http.server`, `urllib.request`) |
| AI | OpenAI-compatible Chat Completions API |
| Dependencies | None |

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
└── .gitignore        # Ignores .env and caches
```

## Prerequisites

- Python 3.10+
- Node.js 18+ (optional, for `npm start`)
- Chrome recommended for voice input
- API key for an OpenAI-compatible endpoint
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

Add your key to `.env`:

```env
AI_API_KEY=your-api-key
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```

## Run locally

```bash
python server.py
```

Or:

```bash
npm start
```

Open **http://127.0.0.1:5500/**. Health check: **/api/health**.

## Deployment

Deploy as a Python web service on Render:

- Repository: https://github.com/sidhinath/Bol_Bindaas_project
- Build command: `pip install -r requirements.txt`
- Start command: `python server.py`
- Health check: `/api/health`
- Environment variables: `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `HOST=0.0.0.0`, `PORT`

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
