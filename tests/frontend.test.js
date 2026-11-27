const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_PATH = path.join(__dirname, "..", "app.js");
const APP_SOURCE = fs.readFileSync(APP_PATH, "utf8");
const PLACEHOLDER = "Your clean, natural English will appear here.";

const ELEMENT_IDS = [
  "inputText",
  "charCount",
  "modelSelect",
  "convertBtn",
  "statusText",
  "speakBtn",
  "outputText",
  "copyBtn",
  "listenBtn",
  "clearBtn",
  "themeToggle",
];

const INITIAL_TEXT = {
  statusText: "Ready",
  speakBtn: "Speak",
  convertBtn: "Convert to English",
};

function makeElement(id) {
  const element = {
    id,
    value: "",
    hidden: false,
    textContent: INITIAL_TEXT[id] || "",
    disabled: false,
    focused: false,
    dataset: {},
    style: {},
    attrs: {},
    classes: new Set(),
    listeners: {},
    span: null,
  };

  element.classList = {
    add(...names) {
      names.forEach((name) => element.classes.add(name));
    },
    remove(...names) {
      names.forEach((name) => element.classes.delete(name));
    },
    toggle(name, force) {
      if (force === undefined) {
        if (element.classes.has(name)) element.classes.delete(name);
        else element.classes.add(name);
      } else if (force) {
        element.classes.add(name);
      } else {
        element.classes.delete(name);
      }
    },
    contains(name) {
      return element.classes.has(name);
    },
  };

  element.addEventListener = (type, handler) => {
    if (!element.listeners[type]) element.listeners[type] = [];
    element.listeners[type].push(handler);
  };

  element.setAttribute = (name, value) => {
    element.attrs[name] = value;
  };

  element.getAttribute = (name) => element.attrs[name];

  element.querySelector = (selector) => (selector === "span" ? element.span : null);

  element.focus = () => {
    element.focused = true;
  };

  element.select = () => {};

  element.remove = () => {};

  return element;
}

const DEFAULT_RESPONSE = () => ({
  ok: true,
  status: 200,
  json: async () => ({ text: "Today I am feeling a little low." }),
});

function loadApp(options = {}) {
  const elements = Object.fromEntries(ELEMENT_IDS.map((id) => [id, makeElement(id)]));
  const fetchCalls = [];
  const storage = new Map();

  if (options.savedTheme) storage.set("theme", options.savedTheme);

  elements.modelSelect.value = "auto";

  // The pasted markup puts the active class on the first pill.
  const tones = options.tonePills || ["Casual", "Professional", "Polite", "Direct", "Empathetic"];
  const tonePills = tones.map((tone, index) => {
    const pill = makeElement(`tone-${tone}`);
    pill.dataset.tone = tone;
    pill.textContent = tone;
    if (index === 0) pill.classList.add("active");
    return pill;
  });

  for (const id of ["speakBtn", "convertBtn"]) {
    const label = makeElement(`${id}-label`);
    label.textContent = INITIAL_TEXT[id];
    elements[id].span = label;
  }

  const document = {
    documentElement: makeElement("html"),
    body: { appendChild() {} },
    createElement: (tag) => makeElement(tag),
    getElementById: (id) => elements[id],
    querySelectorAll: (selector) => (selector === "[data-tone]" ? tonePills : []),
  };

  const window = {
    matchMedia: () => ({ matches: false }),
  };

  if (options.speechRecognition) {
    window.SpeechRecognition = options.speechRecognition;
  }
  if (options.speechSynthesis) {
    window.speechSynthesis = options.speechSynthesis;
  }

  const sandbox = {
    document,
    window,
    localStorage: {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, value),
    },
    navigator: {
      onLine: true,
      clipboard: { writeText: async () => {} },
    },
    SpeechSynthesisUtterance: class SpeechSynthesisUtterance {
      constructor(text) {
        this.text = text;
        this.lang = "";
        this.rate = 1;
      }
    },
    fetch: async (url, init) => {
      fetchCalls.push({ url, init });
      const respond = options.response || DEFAULT_RESPONSE;
      return respond(fetchCalls.length - 1, fetchCalls.at(-1));
    },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    console,
  };
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(APP_SOURCE, sandbox, { filename: APP_PATH });

  return { elements, sandbox, document, fetchCalls, storage, tonePills };
}

async function fire(element, type, event = {}) {
  for (const handler of element.listeners[type] || []) {
    await handler(event);
  }
}

async function tick() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("initial UI state is reset and ready", () => {
  const { elements } = loadApp();

  assert.equal(elements.charCount.textContent, "0 / 4000");
  assert.equal(elements.outputText.textContent, PLACEHOLDER);
  assert.equal(elements.outputText.classList.contains("placeholder"), true);
  assert.equal(elements.copyBtn.disabled, true);
  assert.equal(elements.listenBtn.disabled, true);
  assert.equal(elements.clearBtn.disabled, true);
  assert.equal(elements.convertBtn.span.textContent, "Convert to English");
  assert.equal(elements.speakBtn.hidden, true);
  assert.equal(
    elements.statusText.textContent,
    "Voice input isn't supported here. Typing works perfectly."
  );
});

test("tone pills lowercase the selected tone and update the active state", async () => {
  const { elements, tonePills, fetchCalls } = loadApp();

  assert.equal(tonePills[0].classList.contains("active"), true);
  await fire(tonePills[1], "click");

  assert.equal(tonePills[1].classList.contains("active"), true);
  assert.equal(tonePills[0].classList.contains("active"), false);
  assert.equal(elements.statusText.textContent, "Professional tone selected.");
  assert.equal(elements.statusText.dataset.state, "idle");

  elements.inputText.value = "kal meeting thoda late rakhte hain";
  await fire(elements.convertBtn, "click");
  assert.equal(JSON.parse(fetchCalls[0].init.body).tone, "professional");
});

test("empty input shows a validation error and does not call the API", async () => {
  const { elements, fetchCalls } = loadApp();
  elements.inputText.value = "   ";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 0);
  assert.equal(elements.statusText.textContent, "Please write or speak your thought first.");
  assert.equal(elements.statusText.dataset.state, "error");
  assert.equal(elements.inputText.focused, true);
});

test("successful conversion posts trimmed text, tone, and mapped provider", async () => {
  const { elements, fetchCalls } = loadApp({
    response: () => ({
      ok: true,
      status: 200,
      json: async () => ({ text: "  Today I am feeling a little low.  ", provider: "gemini" }),
    }),
  });
  elements.inputText.value = "  aaj mera mood thoda off hai  ";
  elements.modelSelect.value = "fast";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, "/api/convert");
  assert.equal(fetchCalls[0].init.method, "POST");
  assert.equal(fetchCalls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), {
    text: "aaj mera mood thoda off hai",
    tone: "casual",
    provider: "groq",
  });

  assert.equal(elements.outputText.textContent, "Today I am feeling a little low.");
  assert.equal(elements.outputText.classList.contains("placeholder"), false);
  assert.equal(elements.copyBtn.disabled, false);
  assert.equal(elements.listenBtn.disabled, false);
  assert.equal(elements.clearBtn.disabled, false);
  assert.match(
    elements.statusText.textContent,
    /^Done in \d+\.\ds — Gemini — here is your English version\.$/
  );
  assert.equal(elements.statusText.dataset.state, "success");
  assert.equal(elements.convertBtn.disabled, false);
});

test("Pro model maps to Gemini and AI Auto maps to auto", async () => {
  const { elements, fetchCalls } = loadApp();
  elements.inputText.value = "kuch bataon";
  elements.modelSelect.value = "quality";
  await fire(elements.convertBtn, "click");
  assert.equal(JSON.parse(fetchCalls[0].init.body).provider, "gemini");

  elements.modelSelect.value = "auto";
  await fire(elements.convertBtn, "click");
  assert.equal(JSON.parse(fetchCalls[1].init.body).provider, "auto");
});

test("responding provider is shown even when Auto falls back", async () => {
  const { elements } = loadApp({
    response: () => ({
      ok: true,
      status: 200,
      json: async () => ({ text: "Fallback answer.", provider: "openrouter" }),
    }),
  });
  elements.inputText.value = "bataon kya hua";

  await fire(elements.convertBtn, "click");

  assert.match(elements.statusText.textContent, /— OpenRouter — here is your English version\.$/);
});

test("loading state shows elapsed time while waiting and resets afterwards", async () => {
  let release;
  const { elements } = loadApp({
    response: async () => {
      await new Promise((resolve) => { release = resolve; });
      return { ok: true, status: 200, json: async () => ({ text: "Ready." }) };
    },
  });
  elements.inputText.value = "aaj mera mood thoda off hai";

  const pending = fire(elements.convertBtn, "click");
  await tick();

  assert.equal(elements.convertBtn.disabled, true);
  assert.equal(elements.convertBtn.classList.contains("is-busy"), true);
  assert.equal(elements.outputText.classList.contains("is-loading"), true);
  assert.match(elements.statusText.textContent, /^Converting\.\.\. 0\.0s$/);

  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.match(elements.statusText.textContent, /^Converting\.\.\. \d+\.\ds$/);

  release();
  await pending;

  assert.equal(elements.convertBtn.disabled, false);
  assert.equal(elements.convertBtn.classList.contains("is-busy"), false);
  assert.equal(elements.outputText.classList.contains("is-loading"), false);
});

test("API error message is displayed to the user", async () => {
  const { elements } = loadApp({
    response: () => ({
      ok: false,
      status: 502,
      json: async () => ({ error: "Gemini rejected the request." }),
    }),
  });
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(elements.statusText.textContent, "Gemini rejected the request.");
  assert.equal(elements.statusText.dataset.state, "error");
  assert.equal(elements.copyBtn.disabled, true);
});

test("unreadable server response produces a helpful error", async () => {
  const { elements } = loadApp({
    response: () => ({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("bad json");
      },
    }),
  });
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(
    elements.statusText.textContent,
    "The server sent an unreadable response. Check the server terminal."
  );
});

test("empty conversion result is rejected", async () => {
  const { elements } = loadApp({
    response: () => ({ ok: true, status: 200, json: async () => ({ text: "   " }) }),
  });
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(elements.statusText.textContent, "The conversion came back empty. Please try again.");
});

test("offline state prevents an API request", async () => {
  const { elements, sandbox, fetchCalls } = loadApp();
  sandbox.navigator.onLine = false;
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 0);
  assert.equal(
    elements.statusText.textContent,
    "You seem to be offline. Check your connection and try again."
  );
});

test("clear control resets input and output", async () => {
  const { elements } = loadApp();
  elements.inputText.value = "aaj mera mood thoda off hai";
  await fire(elements.convertBtn, "click");

  await fire(elements.clearBtn, "click");

  assert.equal(elements.inputText.value, "");
  assert.equal(elements.charCount.textContent, "0 / 4000");
  assert.equal(elements.outputText.textContent, PLACEHOLDER);
  assert.equal(elements.outputText.classList.contains("placeholder"), true);
  assert.equal(elements.copyBtn.disabled, true);
  assert.equal(elements.listenBtn.disabled, true);
  assert.equal(elements.clearBtn.disabled, true);
  assert.equal(elements.statusText.textContent, "Cleared. Ready for a new thought.");
  assert.equal(elements.inputText.focused, true);
});

test("copy output reports success", async () => {
  const { elements } = loadApp();
  elements.inputText.value = "kuch bataon";
  await fire(elements.convertBtn, "click");

  await fire(elements.copyBtn, "click");

  assert.equal(elements.statusText.textContent, "Copied!");
  assert.equal(elements.statusText.dataset.state, "success");
});

test("listen output speaks English and tracks playback state", async () => {
  const speechSynthesis = { cancel() {}, speak(utterance) { this.last = utterance; utterance.onstart(); } };
  const { elements } = loadApp({ speechSynthesis });
  elements.inputText.value = "kuch bataon";
  await fire(elements.convertBtn, "click");

  await fire(elements.listenBtn, "click");

  assert.equal(speechSynthesis.last.text, "Today I am feeling a little low.");
  assert.equal(speechSynthesis.last.lang, "en-US");
  assert.equal(elements.listenBtn.classList.contains("is-active"), true);
  assert.equal(elements.statusText.textContent, "Playing...");

  speechSynthesis.last.onend();
  assert.equal(elements.listenBtn.classList.contains("is-active"), false);
});

test("theme toggle switches theme and persists it", async () => {
  const { elements, document, storage } = loadApp();

  await fire(elements.themeToggle, "click");

  assert.equal(document.documentElement.dataset.theme, "dark");
  assert.equal(storage.get("theme"), "dark");
  assert.equal(elements.themeToggle.getAttribute("aria-label"), "Switch to light theme");
});

test("saved dark theme is restored on load", () => {
  const { document } = loadApp({ savedTheme: "dark" });
  assert.equal(document.documentElement.dataset.theme, "dark");
});

test("speech recognition uses hi-IN and updates the textarea from transcripts", async () => {
  const instances = [];

  class FakeSpeechRecognition {
    constructor() {
      instances.push(this);
      this.lang = "";
      this.continuous = false;
      this.interimResults = false;
      this.maxAlternatives = 0;
      this.started = false;
      this.stopped = false;
    }

    start() {
      this.started = true;
      if (this.onstart) this.onstart();
    }

    stop() {
      this.stopped = true;
      if (this.onend) this.onend();
    }
  }

  const { elements } = loadApp({ speechRecognition: FakeSpeechRecognition });
  assert.equal(elements.speakBtn.hidden, false);

  await fire(elements.speakBtn, "click");

  const recognition = instances[0];
  assert.equal(recognition.lang, "hi-IN");
  assert.equal(recognition.continuous, true);
  assert.equal(recognition.interimResults, true);
  assert.equal(recognition.maxAlternatives, 1);
  assert.equal(recognition.started, true);
  assert.equal(elements.speakBtn.span.textContent, "Stop listening");
  assert.equal(elements.speakBtn.classList.contains("is-active"), true);

  const finalResult = [{ transcript: "namaste" }];
  finalResult.isFinal = true;
  recognition.onresult({
    resultIndex: 0,
    results: [finalResult, Object.assign([{ transcript: "duniya" }], { isFinal: false })],
  });

  assert.equal(elements.inputText.value, "namaste duniya");
  assert.equal(elements.charCount.textContent, `${elements.inputText.value.length} / 4000`);

  await fire(elements.speakBtn, "click");

  assert.equal(recognition.stopped, true);
  assert.equal(elements.speakBtn.span.textContent, "Speak");
  assert.equal(elements.speakBtn.classList.contains("is-active"), false);
});

test("Ctrl+Enter starts a conversion", async () => {
  const { elements, fetchCalls } = loadApp();
  elements.inputText.value = "yaar plan cancel ho gaya";

  await fire(elements.inputText, "keydown", { ctrlKey: true, metaKey: false, key: "Enter" });
  await tick();

  assert.equal(fetchCalls.length, 1);
  assert.equal(JSON.parse(fetchCalls[0].init.body).text, "yaar plan cancel ho gaya");
});
