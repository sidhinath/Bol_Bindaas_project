const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const app = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const styleBlock = html.match(/<style>([\s\S]*?)<\/style>/);
const css = styleBlock ? styleBlock[1] : "";

test("every element requested by app.js exists in index.html", () => {
  const ids = [...app.matchAll(/getElementById\("([^"]+)"\)/g)].map((match) => match[1]);

  assert.ok(ids.length > 0, "Expected app.js to reference DOM element IDs");
  for (const id of ids) {
    assert.match(html, new RegExp(`id="${id}"`), `Missing #${id} in index.html`);
  }
});

test("conversion requests go through the app server, locally or from Capacitor", () => {
  assert.match(app, /const LOCAL_API_ENDPOINT\s*=\s*"\/api\/convert"/);
  assert.match(
    app,
    /const DEPLOYED_API_ENDPOINT\s*=\s*"https:\/\/bol-bindaas-project\.onrender\.com\/api\/convert"/
  );
  assert.match(app, /window\.Capacitor/);
  assert.match(app, /capacitor:/);
  assert.match(app, /file:/);
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
  assert.match(html, /class="tone-pill is-active" type="button" data-tone="direct"/);
  assert.match(app, /DEFAULT_TONE\s*=\s*"direct"/);
  assert.match(app, /tone: toneEl\.value/);
  assert.match(app, /querySelectorAll\("\[data-tone\]"\)/);
});

test("all CSS is embedded inline with no external stylesheet or Tailwind dependency", () => {
  assert.ok(styleBlock, "Expected a <style> block in index.html");
  assert.doesNotMatch(html, /<link[^>]*rel=["']stylesheet["'][^>]*>/i);
  assert.doesNotMatch(html, /tailwind/i);
  assert.match(css, /max-width:\s*1180px/);
  assert.match(css, /font-family:\s*Inter/);
  assert.doesNotMatch(css, /font-family:\s*['"]?(serif|georgia|times)/i);
});

test("dark and light themes use the specified palette and gradient CTA", () => {
  assert.match(css, /\[data-theme="dark"\]/);
  assert.match(css, /--page:\s*#090d16/);
  assert.match(css, /--surface:\s*#111827/);
  assert.match(css, /--input:\s*#0d1320/);
  assert.match(css, /--text:\s*#f8fafc/);
  assert.match(css, /\[data-theme="light"\]/);
  assert.match(css, /body\.light-theme/);
  assert.match(css, /#6366f1/);
  assert.match(css, /#8b5cf6/);
});

test("workspace follows the centered split-pane design contract", () => {
  assert.match(css, /grid-template-columns:\s*1fr 1fr/);
  assert.match(css, /font-size:\s*18px/);
  assert.match(css, /font-size:\s*14px/);
  assert.match(css, /svg\s*\{[^}]*width:\s*18px[^}]*height:\s*18px/s);
  assert.match(html, /class="skeleton"/);
  assert.match(html, /id="inputClearBtn"/);
  assert.match(html, /id="convertBtn"/);
  assert.match(html, /id="status" data-state="idle"/);
});

test("mobile layout stacks panes and scrolls tone pills without clipping", () => {
  assert.match(css, /@media\s*\(max-width:\s*820px\)/);
  assert.match(css, /grid-template-columns:\s*1fr;/);
  assert.match(css, /overflow-x:\s*auto/);
  assert.match(css, /flex-wrap:\s*nowrap/);
  assert.match(css, /white-space:\s*nowrap/);
  assert.match(css, /grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(css, /grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(css, /\.output-actions #clearBtn\s*\{[^}]*padding-left:\s*6px/s);
});

test("convert and status controls live in the input pane before the output pane", () => {
  const inputStart = html.indexOf('class="pane pane--input"');
  const outputStart = html.indexOf('id="outputCard"');
  assert.ok(inputStart > -1 && outputStart > inputStart);
  const inputPane = html.slice(inputStart, outputStart);
  for (const id of ["micBtn", "convertBtn", "convertLabel", "status"]) {
    assert.match(inputPane, new RegExp(`id="${id}"`), `#${id} must be inside the input pane`);
  }
});

test("footer uses the current BolBindaas copyright line", () => {
  assert.ok(
    html.includes("© 2026 BolBindaas — Say it in Hinglish. Write it in English.")
  );
});

test("provider options and the response badge are wired up", () => {
  for (const provider of ["auto", "gemini", "openai", "groq", "openrouter"]) {
    assert.match(html, new RegExp(`<option value="${provider}">`));
  }
  assert.match(html, /id="providerBadge"/);
  assert.match(css, /#providerBadge\s*\{[^}]*display:\s*none\s*!important/s);
  assert.match(app, /provider: providerEl\.value \|\| "auto"/);
  assert.match(app, /data\.provider/);
});
