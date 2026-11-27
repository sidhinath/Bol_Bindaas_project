/* BolBindaas — frontend logic.
   The AI key never appears here: all conversions go through /api/convert. */

const API_ENDPOINT = "/api/convert";
const MAX_CHARS = 4000;
const DEFAULT_TONE = "direct";
const PLACEHOLDER = "Your clean, natural English will appear here.";
const PROVIDER_LABELS = {
    gemini: "Gemini",
    openai: "OpenAI",
    groq: "Groq",
    openrouter: "OpenRouter"
};

// The compact model picker maps to the providers supported by server.py.
const MODEL_PROVIDERS = {
    auto: "auto",
    fast: "groq",
    quality: "gemini"
};

const inputEl = document.getElementById("inputText");
const counterEl = document.getElementById("charCount");
const modelSelect = document.getElementById("modelSelect");
const convertBtn = document.getElementById("convertBtn");
const statusEl = document.getElementById("statusText");
const speakBtn = document.getElementById("speakBtn");
const outputText = document.getElementById("outputText");
const copyBtn = document.getElementById("copyBtn");
const listenBtn = document.getElementById("listenBtn");
const clearBtn = document.getElementById("clearBtn");
const themeToggle = document.getElementById("themeToggle");

let currentOutput = "";
let currentTone = DEFAULT_TONE;
let statusTimer;
let busyTimer;
let requestStartedAt = 0;

// Speech recognition state
let recognition = null;
let listening = false;
let speechError = false;
let baseText = "";
let finalTranscript = "";

/* ---------- Small UI helpers ---------- */

function labelOf(button) {
    return button.querySelector("span") || button;
}

function setStatus(message, state = "idle") {
    clearTimeout(statusTimer);
    statusEl.textContent = message;
    statusEl.dataset.state = state;
}

function updateCounter() {
    const count = inputEl.value.length;
    counterEl.textContent = `${count} / ${MAX_CHARS}`;
    counterEl.style.color = count > MAX_CHARS * 0.9 ? "var(--warning)" : "";
}

function setBusy(busy) {
    convertBtn.disabled = busy;
    convertBtn.classList.toggle("is-busy", busy);
}

function startBusyFeedback() {
    clearInterval(busyTimer);
    requestStartedAt = Date.now();
    setStatus("Converting... 0.0s", "loading");
    busyTimer = setInterval(() => {
        setStatus(`Converting... ${elapsedSeconds()}s`, "loading");
    }, 100);
}

function stopBusyFeedback() {
    clearInterval(busyTimer);
    busyTimer = null;
}

function elapsedSeconds() {
    return ((Date.now() - requestStartedAt) / 1000).toFixed(1);
}

function setupTonePills() {
    const pills = typeof document.querySelectorAll === "function"
        ? document.querySelectorAll("[data-tone]")
        : [];

    pills.forEach((pill) => {
        const tone = String(pill.dataset.tone || "").toLowerCase();
        if (tone && pill.classList.contains("active")) currentTone = tone;

        pill.addEventListener("click", () => {
            if (tone) currentTone = tone;
            pills.forEach((other) => other.classList.toggle("active", other === pill));
            setStatus(`${pill.textContent.trim()} tone selected.`, "idle");
        });
    });

    // Keep exactly one pill highlighted, even if the markup has none active.
    const activePills = Array.prototype.filter.call(pills, (pill) => pill.classList.contains("active"));
    if (!activePills.length && pills.length) {
        pills[0].classList.add("active");
        currentTone = String(pills[0].dataset.tone || DEFAULT_TONE).toLowerCase();
    }
}

function clearOutput() {
    currentOutput = "";
    outputText.textContent = PLACEHOLDER;
    outputText.classList.add("placeholder");
    outputText.classList.remove("is-loading");
    [copyBtn, listenBtn, clearBtn].forEach((button) => { button.disabled = true; });
    listenBtn.classList.remove("is-active");
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

/* ---------- Conversion ---------- */

async function convertToEnglish() {
    const text = inputEl.value.trim();

    if (!text) {
        setStatus("Please write or speak your thought first.", "error");
        inputEl.focus();
        return;
    }
    if (text.length > MAX_CHARS) {
        setStatus(`Please keep your thought under ${MAX_CHARS} characters.`, "error");
        return;
    }

    // Don't let the transcript keep changing while we send the text.
    if (listening && recognition) recognition.stop();

    if (!navigator.onLine) {
        setStatus("You seem to be offline. Check your connection and try again.", "error");
        return;
    }

    setBusy(true);
    outputText.classList.add("is-loading");
    startBusyFeedback();

    try {
        const selected = modelSelect.value || "auto";
        const response = await fetch(API_ENDPOINT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text,
                tone: currentTone,
                provider: MODEL_PROVIDERS[selected] || "auto"
            })
        });

        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error("The server sent an unreadable response. Check the server terminal.");
        }

        if (!response.ok) {
            throw new Error(data && data.error ? data.error : `Request failed (${response.status}).`);
        }

        const result = data && typeof data.text === "string" ? data.text.trim() : "";
        if (!result) {
            throw new Error("The conversion came back empty. Please try again.");
        }

        currentOutput = result;
        outputText.textContent = result;
        outputText.classList.remove("placeholder");
        [copyBtn, listenBtn, clearBtn].forEach((button) => { button.disabled = false; });

        // Show which provider actually answered (Auto may have fallen back).
        const usedProvider = data && data.provider ? data.provider : "";
        const providerLabel = usedProvider
            ? (PROVIDER_LABELS[usedProvider] || usedProvider)
            : "";
        setStatus(
            `Done in ${elapsedSeconds()}s${providerLabel ? ` — ${providerLabel}` : ""} — here is your English version.`,
            "success"
        );
    } catch (error) {
        const message = error instanceof TypeError
            ? "Cannot reach the app server. Is server.py running?"
            : error.message;
        setStatus(message || "Something went wrong. Please try again.", "error");
    } finally {
        stopBusyFeedback();
        setBusy(false);
        outputText.classList.remove("is-loading");
    }
}

/* ---------- Output actions ---------- */

async function copyOutput() {
    if (!currentOutput) return;

    try {
        await navigator.clipboard.writeText(currentOutput);
    } catch {
        // Fallback for browsers without the async Clipboard API.
        const field = document.createElement("textarea");
        field.value = currentOutput;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        const copied = typeof document.execCommand === "function" && document.execCommand("copy");
        field.remove();
        if (!copied) {
            setStatus("Could not copy automatically. Please select the text.", "error");
            return;
        }
    }

    setStatus("Copied!", "success");
}

function listenOutput() {
    if (!currentOutput) return;

    if (!("speechSynthesis" in window)) {
        setStatus("Speech playback isn't supported in this browser.", "error");
        return;
    }

    const synth = window.speechSynthesis;
    synth.cancel(); // Stop any earlier playback before starting a new one.

    const utterance = new SpeechSynthesisUtterance(currentOutput);
    utterance.lang = "en-US";
    utterance.rate = 1;

    utterance.onstart = () => {
        listenBtn.classList.add("is-active");
        setStatus("Playing...", "loading");
    };
    utterance.onend = () => {
        listenBtn.classList.remove("is-active");
        setStatus("");
    };
    utterance.onerror = () => {
        listenBtn.classList.remove("is-active");
        setStatus("Could not play the audio.", "error");
    };

    synth.speak(utterance);
}

function clearAll() {
    if (listening && recognition) recognition.stop();
    inputEl.value = "";
    baseText = "";
    finalTranscript = "";
    updateCounter();
    clearOutput();
    setStatus("Cleared. Ready for a new thought.", "idle");
    inputEl.focus();
}

/* ---------- Voice input (Web Speech API) ---------- */

function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        speakBtn.hidden = true;
        setStatus("Voice input isn't supported here. Typing works perfectly.", "idle");
        return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "hi-IN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        listening = true;
        speechError = false;
        speakBtn.classList.add("is-active");
        speakBtn.setAttribute("aria-pressed", "true");
        labelOf(speakBtn).textContent = "Stop listening";
        setStatus("Listening... speak your thought in Hinglish.", "loading");
    };

    recognition.onresult = (event) => {
        let interim = "";

        for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i];
            const transcript = result[0] ? result[0].transcript : "";
            if (result.isFinal) {
                finalTranscript += `${transcript} `;
            } else {
                interim += transcript;
            }
        }

        const spoken = `${finalTranscript}${interim}`.trim();
        inputEl.value = spoken ? `${baseText}${baseText ? " " : ""}${spoken}` : baseText;
        updateCounter();
    };

    recognition.onerror = (event) => {
        speechError = true;
        const messages = {
            "not-allowed": "Microphone permission was denied. Allow it in your browser settings.",
            "service-not-allowed": "Voice input is blocked by this browser.",
            "no-speech": "I didn't catch that. Please try speaking again.",
            network: "Voice input needs an internet connection.",
            aborted: "Voice input was cancelled."
        };
        setStatus(messages[event.error] || "Voice input failed. You can still type your thought.", "error");
    };

    recognition.onend = () => {
        listening = false;
        speakBtn.classList.remove("is-active");
        speakBtn.setAttribute("aria-pressed", "false");
        labelOf(speakBtn).textContent = "Speak";
        if (!speechError) {
            setStatus("Voice input stopped. Edit if you like, then convert.", "idle");
        }
    };

    speakBtn.addEventListener("click", () => {
        if (listening) {
            recognition.stop();
            return;
        }

        baseText = inputEl.value.trimEnd();
        finalTranscript = "";
        speechError = false;

        try {
            recognition.start();
        } catch {
            setStatus("Could not start voice input. Please try again.", "error");
        }
    });
}

/* ---------- Theme ---------- */

function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    themeToggle.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
    );
}

try {
    const saved = localStorage.getItem("theme");
    if (saved === "dark" || saved === "light") applyTheme(saved);
} catch {
    // Storage can be blocked in private mode; the app still works.
}

themeToggle.addEventListener("click", () => {
    const systemPrefersDark = window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches;
    const current = document.documentElement.dataset.theme || (systemPrefersDark ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
        localStorage.setItem("theme", next);
    } catch {
        // Ignore storage errors.
    }
});

/* ---------- Wire up ---------- */

inputEl.addEventListener("input", updateCounter);
inputEl.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") convertToEnglish();
});
convertBtn.addEventListener("click", convertToEnglish);
copyBtn.addEventListener("click", copyOutput);
listenBtn.addEventListener("click", listenOutput);
clearBtn.addEventListener("click", clearAll);

setupTonePills();
setupSpeechRecognition();
clearOutput();
updateCounter();
