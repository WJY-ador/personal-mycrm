'use strict';
// The app's copy of the web dashboard's tokens (server/ui/src/shared/tokens.css is the one source; CI checks it).
// src/tokens.css is a generated copy (scripts/sync-tokens.cjs); these checks fail when it drifts. The connection window
// that used it is gone (spec 2026-11-13); the copy stays while CI's sync-tokens --check reads it.
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
