const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_PATH = path.join(__dirname, "..", "app.js");
const APP_SOURCE = fs.readFileSync(APP_PATH, "utf8");

const ELEMENT_IDS = [
  "inputText",
  "counter",
  "tone",
  "convertBtn",
  "convertLabel",
  "status",
  "micBtn",
  "micLabel",
  "micNote",
  "listening",
  "outputCard",
  "outputText",
  "outputStatus",
  "copyBtn",
  "listenBtn",
  "clearBtn",
  "themeToggle",
];

const INITIAL_TEXT = {
  convertLabel: "Convert to English",
  micLabel: "Speak",
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

  element.focus = () => {
    element.focused = true;
  };

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

  const document = {
    documentElement: makeElement("html"),
    body: { appendChild() {} },
    createElement: (tag) => makeElement(tag),
    getElementById: (id) => elements[id],
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

  return { elements, sandbox, document, fetchCalls, storage };
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

  assert.equal(elements.counter.textContent, "0 / 4000");
  assert.equal(elements.outputText.textContent, "Your clean, natural English will appear here.");
  assert.equal(elements.outputText.classList.contains("is-placeholder"), true);
  assert.equal(elements.copyBtn.disabled, true);
  assert.equal(elements.listenBtn.disabled, true);
  assert.equal(elements.clearBtn.disabled, true);
  assert.equal(elements.convertLabel.textContent, "Convert to English");
  assert.equal(elements.micBtn.hidden, true);
  assert.equal(elements.micNote.hidden, false);
});

test("empty input shows a validation error and does not call the API", async () => {
  const { elements, fetchCalls } = loadApp();
  elements.inputText.value = "   ";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 0);
  assert.equal(elements.status.textContent, "Please write or speak your thought first.");
  assert.equal(elements.status.dataset.state, "error");
  assert.equal(elements.inputText.focused, true);
});

test("successful conversion posts trimmed text and tone, then shows English", async () => {
  const { elements, fetchCalls } = loadApp({
    response: () => ({
      ok: true,
      status: 200,
      json: async () => ({ text: "  Today I am feeling a little low.  " }),
    }),
  });
  elements.inputText.value = "  aaj mera mood thoda off hai  ";
  elements.tone.value = "formal";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, "/api/convert");
  assert.equal(fetchCalls[0].init.method, "POST");
  assert.equal(fetchCalls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), {
    text: "aaj mera mood thoda off hai",
    tone: "formal",
  });

  assert.equal(elements.outputText.textContent, "Today I am feeling a little low.");
  assert.equal(elements.outputText.classList.contains("is-placeholder"), false);
  assert.equal(elements.copyBtn.disabled, false);
  assert.equal(elements.listenBtn.disabled, false);
  assert.equal(elements.clearBtn.disabled, false);
  assert.match(elements.status.textContent, /^Done in \d+\.\ds — here is your English version\.$/);
  assert.equal(elements.status.dataset.state, "success");
  assert.equal(elements.convertLabel.textContent, "Convert to English");
  assert.equal(elements.convertBtn.disabled, false);
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
  assert.equal(elements.outputCard.classList.contains("is-loading"), true);
  assert.match(elements.convertLabel.textContent, /^Converting\.\.\. 0\.0s$/);

  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.match(elements.convertLabel.textContent, /^Converting\.\.\. \d+\.\ds$/);

  release();
  await pending;

  assert.equal(elements.convertLabel.textContent, "Convert to English");
  assert.equal(elements.convertBtn.disabled, false);
  assert.equal(elements.outputCard.classList.contains("is-loading"), false);
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

  assert.equal(elements.status.textContent, "Gemini rejected the request.");
  assert.equal(elements.status.dataset.state, "error");
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
    elements.status.textContent,
    "The server sent an unreadable response. Check the server terminal."
  );
});

test("empty conversion result is rejected", async () => {
  const { elements } = loadApp({
    response: () => ({ ok: true, status: 200, json: async () => ({ text: "   " }) }),
  });
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(elements.status.textContent, "The conversion came back empty. Please try again.");
});

test("offline state prevents an API request", async () => {
  const { elements, sandbox, fetchCalls } = loadApp();
  sandbox.navigator.onLine = false;
  elements.inputText.value = "kuch bataon";

  await fire(elements.convertBtn, "click");

  assert.equal(fetchCalls.length, 0);
  assert.equal(elements.status.textContent, "You seem to be offline. Check your connection and try again.");
});

test("clear control resets input and output", async () => {
  const { elements } = loadApp();
  elements.inputText.value = "aaj mera mood thoda off hai";
  await fire(elements.convertBtn, "click");

  await fire(elements.clearBtn, "click");

  assert.equal(elements.inputText.value, "");
  assert.equal(elements.counter.textContent, "0 / 4000");
  assert.equal(elements.outputText.textContent, "Your clean, natural English will appear here.");
  assert.equal(elements.outputText.classList.contains("is-placeholder"), true);
  assert.equal(elements.copyBtn.disabled, true);
  assert.equal(elements.listenBtn.disabled, true);
  assert.equal(elements.clearBtn.disabled, true);
  assert.equal(elements.status.textContent, "Cleared. Ready for a new thought.");
  assert.equal(elements.inputText.focused, true);
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
  assert.equal(elements.micBtn.hidden, false);

  await fire(elements.micBtn, "click");

  const recognition = instances[0];
  assert.equal(recognition.lang, "hi-IN");
  assert.equal(recognition.continuous, true);
  assert.equal(recognition.interimResults, true);
  assert.equal(recognition.maxAlternatives, 1);
  assert.equal(recognition.started, true);
  assert.equal(elements.micLabel.textContent, "Stop listening");
  assert.equal(elements.listening.hidden, false);

  const finalResult = [{ transcript: "namaste" }];
  finalResult.isFinal = true;
  recognition.onresult({
    resultIndex: 0,
    results: [finalResult, Object.assign([{ transcript: "duniya" }], { isFinal: false })],
  });

  assert.equal(elements.inputText.value, "namaste duniya");
  assert.equal(elements.counter.textContent, `${elements.inputText.value.length} / 4000`);

  await fire(elements.micBtn, "click");

  assert.equal(recognition.stopped, true);
  assert.equal(elements.micLabel.textContent, "Speak");
  assert.equal(elements.listening.hidden, true);
});

test("Ctrl+Enter starts a conversion", async () => {
  const { elements, fetchCalls } = loadApp();
  elements.inputText.value = "yaar plan cancel ho gaya";

  await fire(elements.inputText, "keydown", { ctrlKey: true, metaKey: false, key: "Enter" });
  await tick();

  assert.equal(fetchCalls.length, 1);
  assert.equal(JSON.parse(fetchCalls[0].init.body).text, "yaar plan cancel ho gaya");
});
