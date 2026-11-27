const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const app = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");

test("every element requested by app.js exists in index.html", () => {
  const ids = [...app.matchAll(/getElementById\("([^"]+)"\)/g)].map((match) => match[1]);

  assert.ok(ids.length > 0, "Expected app.js to reference DOM element IDs");
  for (const id of ids) {
    assert.match(html, new RegExp(`id="${id}"`), `Missing #${id} in index.html`);
  }
});

test("conversion requests go to the server route, not directly to an AI provider", () => {
  assert.match(app, /const API_ENDPOINT\s*=\s*"\/api\/convert"/);
  assert.doesNotMatch(app, /generativelanguage|api\.openai|Authorization|Bearer/);
});

test("voice input is configured for Hindi and output speech for English", () => {
  assert.match(app, /recognition\.lang\s*=\s*"hi-IN"/);
  assert.match(app, /utterance\.lang\s*=\s*"en-US"/);
});

test("tone pills in the markup match the values used by the app and server", () => {
  for (const tone of ["casual", "professional", "polite", "direct", "empathetic"]) {
    assert.match(html, new RegExp(`data-tone="${tone}"`));
  }
  assert.match(html, /id="tone" value="direct"/);
  assert.match(app, /DEFAULT_TONE\s*=\s*"direct"/);
  assert.match(app, /tone: toneEl\.value/);
  assert.match(app, /querySelectorAll\("\[data-tone\]"\)/);
});

test("workspace follows the high-end writing workspace design contract", () => {
  assert.match(css, /max-width:\s*1180px/);
  assert.match(css, /--bg:\s*#090D16/);
  assert.match(css, /--surface:\s*#111827/);
  assert.match(css, /rgba\(255, 255, 255, 0\.08\)/);
  assert.match(css, /font-family:\s*Inter/);
  assert.doesNotMatch(html, /serif/i);
  assert.match(css, /grid-template-columns:\s*minmax\(0, 1fr\) 1px minmax\(0, 1fr\)/);
  assert.match(css, /font-size:\s*1\.125rem/);
  assert.match(html, /class="skeleton"/);
  assert.match(html, /id="inputClearBtn"/);
  assert.match(html, /id="convertBtn"/);
});

test("provider options and the response badge are wired up", () => {
  for (const provider of ["auto", "gemini", "openai", "groq", "openrouter"]) {
    assert.match(html, new RegExp(`<option value="${provider}">`));
  }
  assert.match(html, /id="providerBadge"/);
  assert.match(app, /provider: providerEl\.value \|\| "auto"/);
  assert.match(app, /data\.provider/);
});
