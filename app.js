/* BolBindaas — frontend logic.
   The AI key never appears here: all conversions go through /api/convert. */

const LOCAL_API_ENDPOINT = "/api/convert";
const DEPLOYED_API_ENDPOINT = "https://bol-bindaas-project.onrender.com/api/convert";

// Capacitor's Android WebView may use a custom scheme, a file URL, or expose
// the native bridge as window.Capacitor. In every native case, call Render.
const isCapacitorRuntime =
    typeof window !== "undefined" &&
    (Boolean(window.Capacitor) ||
        Boolean(
            window.location &&
                ["capacitor:", "file:"].includes(window.location.protocol)
        ));

const API_ENDPOINT = isCapacitorRuntime
    ? DEPLOYED_API_ENDPOINT
    : LOCAL_API_ENDPOINT;

const MAX_CHARS = 4000;
const DEFAULT_TONE = "direct";
const PLACEHOLDER = "Your clean, natural English will appear here.";
const PROVIDER_LABELS = {
    gemini: "Gemini",
    openai: "OpenAI",
    groq: "Groq",
    openrouter: "OpenRouter"
};

const inputEl = document.getElementById("inputText");
const counterEl = document.getElementById("counter");
const toneEl = document.getElementById("tone");
const providerEl = document.getElementById("provider");
const convertBtn = document.getElementById("convertBtn");
const convertLabel = document.getElementById("convertLabel");
const statusEl = document.getElementById("status");

const inputClearBtn = document.getElementById("inputClearBtn");
const micBtn = document.getElementById("micBtn");
const micLabel = document.getElementById("micLabel");
const micNote = document.getElementById("micNote");
const listeningEl = document.getElementById("listening");

const outputCard = document.getElementById("outputCard");
const outputText = document.getElementById("outputText");
const outputStatus = document.getElementById("outputStatus");
const providerBadge = document.getElementById("providerBadge");
const copyBtn = document.getElementById("copyBtn");
const listenBtn = document.getElementById("listenBtn");
const clearBtn = document.getElementById("clearBtn");
const themeToggle = document.getElementById("themeToggle");

let currentOutput = "";
let statusTimer;
let outputStatusTimer;
let busyTimer;
let requestStartedAt = 0;

// Speech recognition state
let recognition = null;
let listening = false;
let speechError = false;
let baseText = "";
let finalTranscript = "";

/* ---------- Small UI helpers ---------- */

function setStatus(message, state = "idle") {
    clearTimeout(statusTimer);
    statusEl.textContent = message;
    statusEl.dataset.state = state;
}

function setOutputStatus(message, state = "idle") {
    clearTimeout(outputStatusTimer);
    outputStatus.textContent = message;
    outputStatus.dataset.state = state;
}

function flashOutputStatus(message, state = "success") {
    setOutputStatus(message, state);
    outputStatusTimer = setTimeout(() => setOutputStatus(""), 2000);
}

function updateCounter() {
    const count = inputEl.value.length;
    counterEl.textContent = `${count} / ${MAX_CHARS}`;
    counterEl.style.color = count > MAX_CHARS * 0.9 ? "var(--warning)" : "";
}

function setBusy(busy) {
    convertBtn.disabled = busy;
    convertBtn.classList.toggle("is-busy", busy);
    if (!busy) convertLabel.textContent = "Convert to English";
}

function startBusyFeedback() {
    clearInterval(busyTimer);
    requestStartedAt = Date.now();
    convertLabel.textContent = "Converting... 0.0s";
    busyTimer = setInterval(() => {
        const seconds = ((Date.now() - requestStartedAt) / 1000).toFixed(1);
        convertLabel.textContent = `Converting... ${seconds}s`;
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
    if (!toneEl.value) toneEl.value = DEFAULT_TONE;

    const pills = typeof document.querySelectorAll === "function"
        ? document.querySelectorAll("[data-tone]")
        : [];

    pills.forEach((pill) => {
        if (pill.dataset.tone === toneEl.value) pill.classList.add("is-active");
        pill.addEventListener("click", () => {
            toneEl.value = pill.dataset.tone;
            pills.forEach((other) => other.classList.toggle("is-active", other === pill));
            setStatus(`${pill.textContent.trim()} tone selected.`, "idle");
        });
    });
}

function clearInput() {
    if (listening && recognition) recognition.stop();
    inputEl.value = "";
    baseText = "";
    finalTranscript = "";
    updateCounter();
    setStatus("Input cleared. Ready to write again.", "idle");
    inputEl.focus();
}

function clearOutput() {
    currentOutput = "";
    outputText.textContent = PLACEHOLDER;
    outputText.classList.add("is-placeholder");
    outputCard.classList.remove("is-loading");
    [copyBtn, listenBtn, clearBtn].forEach((button) => { button.disabled = true; });
    listenBtn.classList.remove("is-active");
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setOutputStatus("");
    providerBadge.textContent = "";
    providerBadge.hidden = true;
}

/* ---------- Conversion ---------- */

async function convertToEnglish(stream) {
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

    // AbortController for 20-second timeout
    const abortCtrl = new AbortController();
    const timeoutTimeout = setTimeout(() => abortCtrl.abort(), 20000);

    setBusy(true);
    startBusyFeedback();
    outputCard.classList.add("is-loading");
    setStatus("Turning your thought into natural English...", "loading");
    setOutputStatus("");

    try {
        const body = {
            text,
            tone: toneEl.value,
            provider: providerEl.value || "auto"
        };

        const response = await fetch(API_ENDPOINT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: abortCtrl.signal
        });

        clearTimeout(timeoutTimeout);

        // Standard JSON mode (existing behaviour).
        if (!stream) {
            let data;
            try {
                data = await response.json();
            } catch {
                throw new Error("The server sent an unreadable response. Check the server terminal.");
            }

            if (!response.ok) {
                throw new Error(data && data.error ? data.error : `Request failed (${response.status}).`);
            }

            const result = (data && typeof data.text === "string" ? data.text : "") || (data && typeof data.translation === "string" ? data.translation : "") || (data && typeof data.output === "string" ? data.output : "").trim();
            if (!result) {
                throw new Error("The conversion came back empty. Please try again.");
            }

            currentOutput = result;
            outputText.textContent = result;
            outputText.classList.remove("is-placeholder");
            [copyBtn, listenBtn, clearBtn].forEach((button) => { button.disabled = false; });

            // Show which provider actually answered (Auto may have fallen back).
            const usedProvider = data && data.provider ? data.provider : "";
            providerBadge.textContent = usedProvider
                ? `Powered by ${PROVIDER_LABELS[usedProvider] || usedProvider}`
                : "";
            providerBadge.hidden = !usedProvider;

            setStatus(`Done in ${elapsedSeconds()}s — here is your English version.`, "success");
            return;
        }

        // Streaming mode: pipe tokens into #outputText as they arrive.
        if (stream && response.body && "stream" in response) {
            const reader = response.body.getReader();
            const textDecoder = new TextDecoder();
            outputCard.classList.add("is-loading");
            setStatus("Streaming translation...", "loading");

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = textDecoder.decode(value);
                // Accumulate and display each received chunk.
                currentOutput += chunk;
                outputText.textContent = currentOutput || PLACEHOLDER;
                outputText.classList.remove("is-placeholder");
                [copyBtn, listenBtn, clearBtn].forEach((button) => { button.disabled = false; });
            }

            setStatus(`Streaming complete — here is your English version.`, "success");
            return;
        }
    } catch (error) {
        const message = error instanceof TypeError
            ? "Cannot reach the app server. Is server.py running?"
            : error.message;
        setStatus(message || "Something went wrong. Please try again.", "error");
    } finally {
        abortCtrl.abort();
        clearTimeout(timeoutTimeout);
        stopBusyFeedback();
        setBusy(false);
        outputCard.classList.remove("is-loading");
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
            flashOutputStatus("Could not copy automatically. Please select the text.", "error");
            return;
        }
    }

    flashOutputStatus("Copied!", "success");
}

function listenOutput() {
    if (!currentOutput) return;

    if (!("speechSynthesis" in window)) {
        flashOutputStatus("Speech playback isn't supported in this browser.", "error");
        return;
    }

    const synth = window.speechSynthesis;
    synth.cancel(); // Stop any earlier playback before starting a new one.

    const utterance = new SpeechSynthesisUtterance(currentOutput);
    utterance.lang = "en-US";
    utterance.rate = 1;

    utterance.onstart = () => {
        listenBtn.classList.add("is-active");
        setOutputStatus("Playing...", "loading");
    };
    utterance.onend = () => {
        listenBtn.classList.remove("is-active");
        setOutputStatus("");
    };
    utterance.onerror = () => {
        listenBtn.classList.remove("is-active");
        flashOutputStatus("Could not play the audio.", "error");
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
        micBtn.hidden = true;
        micNote.hidden = false;
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
        micBtn.classList.add("is-listening");
        micBtn.setAttribute("aria-pressed", "true");
        micLabel.textContent = "Stop listening";
        listeningEl.hidden = false;
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
        micBtn.classList.remove("is-listening");
        micBtn.setAttribute("aria-pressed", "false");
        micLabel.textContent = "Speak";
        listeningEl.hidden = true;
        if (!speechError) {
            setStatus("Voice input stopped. Edit if you like, then convert.", "idle");
        }
    };

    micBtn.addEventListener("click", () => {
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

// Server warm-up: call /api/health on page load and on input focus
// so Render wakes up while the user is still typing.
function wakeServer() {
    fetch("/api/health")
        .then((r) => r.json())
        .then((data) => {
            // We just want the side-effect of keeping the dyno awake.
        })
        .catch(() => { /* no-op */ });
}
wakeServer();

inputEl.addEventListener("focus", wakeServer);

inputEl.addEventListener("input", updateCounter);
inputEl.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") convertToEnglish();
});
convertBtn.addEventListener("click", convertToEnglish);
inputClearBtn.addEventListener("click", clearInput);
copyBtn.addEventListener("click", copyOutput);
listenBtn.addEventListener("click", listenOutput);
clearBtn.addEventListener("click", clearAll);

setupTonePills();
setupSpeechRecognition();
clearOutput();
updateCounter();
