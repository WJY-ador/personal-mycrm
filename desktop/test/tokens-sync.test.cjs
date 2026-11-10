'use strict';
// The connection window takes the web dashboard's tokens (server/ui/src/shared/tokens.css is the one source).
// src/tokens.css is a generated copy (scripts/sync-tokens.cjs); these checks fail when it drifts or when the
// window's own CSS brings back colour literals, and they keep the page's CSP as strict as before.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { SOURCE, TARGET, COLORS, build, readText } = require('../scripts/sync-tokens.cjs');

const src = name => readText(path.join(__dirname, '..', 'src', name));

test('src/tokens.css equals what the token source gives (run node scripts/sync-tokens.cjs)', () => {
  assert.equal(readText(TARGET), build(readText(SOURCE)));
});

test('the copy carries a light and an OS-dark value for every colour it lists', () => {
  const copy = src('tokens.css');
  const [light, dark] = copy.split('@media (prefers-color-scheme: dark)');
  for (const name of COLORS) {
    assert.match(light, new RegExp(`--${name}: #[0-9A-Fa-f]{6};`), name + ' light');
    assert.match(dark, new RegExp(`--${name}: #[0-9A-Fa-f]{6};`), name + ' dark');
  }
  assert.match(copy, /^\/\* 생성 파일 — 직접 고치지 말고/, 'header says the file is generated');
});

test('build reads the last plain :root value and ignores media-wrapped or :not() variants', () => {
  const css = ':root{--paper:#111111}:root[data-theme="dark"]{--paper:#222222}\n' +
    '@media (prefers-color-scheme: dark){:root{--paper:#999999}}:root:not([data-theme="light"]){--paper:#888888}\n' +
    COLORS.filter(n => n !== 'paper').map(n => `:root{--${n}:#000000}:root[data-theme="dark"]{--${n}:#FFFFFF}`).join('') +
    ':root{--serif:sans-serif;--sp-1:4px}:root{--paper:#333333}';
  const out = build(css);
  assert.match(out, /:root \{\n  color-scheme: light dark;\n  --paper: #333333;/);
  assert.match(out, /@media \(prefers-color-scheme: dark\) \{\n  :root \{\n    --paper: #222222;/);
  assert.match(out, /--sp-1: 4px;/);
  assert.throws(() => build(':root{--paper:#111111}'), /token source lacks/);
});

test('style.css takes colours only from tokens (no hex, rgb or named colour literals)', () => {
  const css = src('style.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(css, /#[0-9A-Fa-f]{3,8}\b/, 'hex literal');
  assert.doesNotMatch(css, /\brgba?\(|\bhsla?\(/, 'rgb/hsl literal');
  assert.doesNotMatch(css, /:\s*(white|black)\b/, 'named colour');
  assert.doesNotMatch(css, /prefers-color-scheme/, 'dark values live in tokens.css');
});

test('every var(--x) style.css uses is defined in the copy', () => {
  const copy = src('tokens.css');
  const used = new Set([...src('style.css').matchAll(/var\(--([a-z0-9-]+)/g)].map(m => m[1]));
  for (const name of used) assert.match(copy, new RegExp(`--${name}:`), `--${name} missing from src/tokens.css (add it to COLORS in scripts/sync-tokens.cjs)`);
});

test('index.html loads tokens.css before style.css and keeps its CSP', () => {
  const html = src('index.html');
  const t = html.indexOf('<link rel="stylesheet" href="tokens.css">');
  const s = html.indexOf('<link rel="stylesheet" href="style.css">');
  assert.ok(t > 0 && s > t, 'tokens.css first');
  assert.ok(html.includes(`content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'"`), 'CSP unchanged');
  assert.doesNotMatch(html, /unsafe-|<style|\sstyle=/);
});
