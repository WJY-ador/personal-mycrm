'use strict';
// Desktop token copy: src/tokens.css is generated from the web dashboard's token file
// (server/ui/src/shared/tokens.css, the one source of truth). The packaged app cannot read server/ui at
// runtime (build.files = src/** + package.json), so the window carries this copy.
//
//   node scripts/sync-tokens.cjs          rewrite src/tokens.css from the source
//   node scripts/sync-tokens.cjs --check  exit 1 when src/tokens.css differs from what the source gives
//
// test/tokens-sync.test.cjs calls build() and fails when the copy drifts.
// Light values come from `:root { ... }` blocks, dark values from `:root[data-theme="dark"] { ... }`
// blocks (later blocks win, as in CSS). The web switches dark with a toggle; this window follows the OS,
// so the dark values go under @media (prefers-color-scheme: dark).
const fs = require('node:fs');
const path = require('node:path');

const SOURCE = path.join(__dirname, '..', '..', 'server', 'ui', 'src', 'shared', 'tokens.css');
const TARGET = path.join(__dirname, '..', 'src', 'tokens.css');
// Colour tokens the window uses: each needs a light and a dark value.
const COLORS = ['paper', 'card', 'ink', 'muted', 'line', 'accent', 'on-accent', 'accent-soft', 'memo', 'memo-bg'];
// Font stack (no dark value). Step tokens (--sp-*, --fs-*, --r-*) are copied whole when the source has them.
const FONTS = ['serif'];
const STEP = /^(sp|fs|r)-[0-9a-z]+$/;

// Read a text file with LF line ends: a Windows checkout may turn the files into CRLF (git autocrlf).
function readText(file) {
  return fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
}

function blocks(css) {
  const light = new Map();
  const dark = new Map();
  // Comments and @media blocks are dropped first: a `:root` inside a media query is not the base value.
  const body = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  // Only the exact selectors `:root` and `:root[data-theme="dark"]`; `:root:not(...)` or media-wrapped variants are skipped.
  const re = /(?<![\w-]):root(\[data-theme="dark"\])?\s*\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(body))) {
    const into = m[1] ? dark : light;
    for (const d of m[2].matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+?)\s*(?:;|$)/g)) into.set(d[1], d[2]);
  }
  return { light, dark };
}

function build(css) {
  const { light, dark } = blocks(css);
  const steps = [...light.keys()].filter(name => STEP.test(name));
  const missing = [];
  for (const name of [...COLORS, ...FONTS]) if (!light.has(name)) missing.push('--' + name + ' (light)');
  for (const name of COLORS) if (!dark.has(name)) missing.push('--' + name + ' (dark)');
  if (missing.length) throw new Error('token source lacks ' + missing.join(', '));
  const line = name => `  --${name}: ${light.get(name)};`;
  return [
    '/* 생성 파일 — 직접 고치지 말고 desktop 폴더에서 `node scripts/sync-tokens.cjs` 로 만든다.',
    '   정본: server/ui/src/shared/tokens.css (데스크톱 창이 쓰는 색, 글꼴 토큰 + 단계 토큰 --sp, --fs, --r 전부). 정본과 다르면 test/tokens-sync.test.cjs 가 실패한다.',
    '   어두운 값 = 정본의 :root[data-theme="dark"] 값. 이 창은 OS 다크 설정을 따른다(prefers-color-scheme). */',
    ':root {',
    '  color-scheme: light dark;',
    ...COLORS.map(line),
    ...FONTS.map(line),
    ...steps.map(line),
    '}',
    '@media (prefers-color-scheme: dark) {',
    '  :root {',
    ...COLORS.map(name => `    --${name}: ${dark.get(name)};`),
    '  }',
    '}',
    '',
  ].join('\n');
}

module.exports = { SOURCE, TARGET, COLORS, build, readText };

if (require.main === module) {
  const want = build(readText(SOURCE));
  if (process.argv.includes('--check')) {
    const have = fs.existsSync(TARGET) ? readText(TARGET) : '';
    if (have !== want) {
      console.error('src/tokens.css differs from server/ui/src/shared/tokens.css — run: node scripts/sync-tokens.cjs');
      process.exit(1);
    }
    console.log('src/tokens.css is in sync');
  } else {
    fs.writeFileSync(TARGET, want);
    console.log('wrote', path.relative(process.cwd(), TARGET));
  }
}
