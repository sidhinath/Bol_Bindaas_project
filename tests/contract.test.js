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

test("capitalized tone pills are normalized for the server before conversion", () => {
  for (const tone of ["Casual", "Professional", "Polite", "Direct", "Empathetic"]) {
    assert.match(html, new RegExp(`data-tone="${tone}"`));
  }
  assert.match(html, /class="tone-pill active" data-tone="Casual"/);
  assert.match(app, /DEFAULT_TONE\s*=\s*"direct"/);
  assert.match(app, /String\(pill\.dataset\.tone \|\| ""\)\.toLowerCase\(\)/);
  assert.match(app, /tone: currentTone/);
  assert.match(app, /querySelectorAll\("\[data-tone\]"\)/);
});

test("workspace follows the split-pane writing workspace design contract", () => {
  assert.match(css, /max-width:\s*1180px/);
  assert.match(css, /--bg-page:\s*#090d16/);
  assert.match(css, /--bg-surface:\s*#111827/);
  assert.match(css, /--bg-input:\s*#0d1320/);
  assert.match(css, /--border-subtle:\s*rgba\(255, 255, 255, 0\.09\)/);
  assert.match(css, /--text-primary:\s*#f8fafc/);
  assert.match(css, /--accent-primary:\s*#6366f1/);
  assert.match(css, /font-family:\s*'Inter'/);
  assert.doesNotMatch(html, /serif/i);
  assert.match(css, /grid-template-columns:\s*1fr 1fr/);
  assert.match(css, /grid-template-columns:\s*1fr;/);
  assert.match(css, /font-size:\s*18px/);
  assert.match(css, /min-height:\s*220px/);
  assert.match(css, /svg\s*\{[^}]*width:\s*18px[^}]*height:\s*18px/s);
  assert.match(css, /\.tone-pill\.active/);
  assert.match(html, /class="split-grid"/);
  assert.match(html, /id="charCount"/);
  assert.match(html, /id="convertBtn"/);
});

test("compact model picker maps to supported server providers", () => {
  assert.match(html, /<option value="auto" selected>AI Auto<\/option>/);
  assert.match(html, /<option value="fast">Fast<\/option>/);
  assert.match(html, /<option value="quality">Pro<\/option>/);
  assert.match(html, /id="modelSelect"/);
  assert.match(app, /fast:\s*"groq"/);
  assert.match(app, /quality:\s*"gemini"/);
  assert.match(app, /provider:\s*MODEL_PROVIDERS\[selected\] \|\| "auto"/);
});
