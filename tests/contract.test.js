const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const app = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");

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

test("tone options in the markup match the selector values used by the app", () => {
  for (const tone of ["normal", "formal", "casual", "poetic"]) {
    assert.match(html, new RegExp(`<option value="${tone}">`));
  }
  assert.match(app, /tone: toneEl\.value/);
});

test("provider options and the response badge are wired up", () => {
  for (const provider of ["auto", "gemini", "openai", "groq", "openrouter"]) {
    assert.match(html, new RegExp(`<option value="${provider}">`));
  }
  assert.match(html, /id="providerBadge"/);
  assert.match(app, /provider: providerEl\.value \|\| "auto"/);
  assert.match(app, /data\.provider/);
});
