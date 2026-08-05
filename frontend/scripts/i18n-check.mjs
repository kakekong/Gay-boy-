/**
 * Keep `src/i18n/id.ts` honest.
 *
 * The dictionary is keyed on the exact English string in the JSX, which is
 * both what makes it easy to write and what makes it easy to break: rewording
 * a label leaves a dictionary entry pointing at a string that no longer
 * exists, and the screen quietly falls back to English with nothing to show
 * for it. Neither failure is visible in a diff.
 *
 *   node scripts/i18n-check.mjs          report
 *   node scripts/i18n-check.mjs --strict exit 1 on any stale entry
 *
 * Untranslated strings are reported but never fail the check — shipping a new
 * English string before its translation is normal, and `T()` handles it.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const STRICT = process.argv.includes('--strict');

const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.tsx')) files.push(p);
  }
})(SRC);

// Two shapes reach the dictionary:
//   T("Save changes")          a literal in the JSX
//   T(tab.label)               a display field off a config object, looked up
//                              at render time because the object itself is
//                              built at module load, before any language
//                              toggle can matter
// The first is found by its literal; the second needs the string collected
// from wherever that object is declared.
const used = new Set();
const DISPLAY = /^(label|hint|title|desc|description|subtitle|heading|placeholder|caption|tooltip|blurb)$/;
for (const f of files) {
  const s = fs.readFileSync(f, 'utf8');
  for (const m of s.matchAll(/\bT\(\s*("(?:[^"\\]|\\.)*")\s*\)/g)) {
    try { used.add(JSON.parse(m[1])); } catch { /* not a plain literal */ }
  }
  // Does this file look up a display field dynamically? If so its own config
  // literals are dictionary keys.
  if (!/\bT\([A-Za-z_$][\w$.]*\.(label|hint|title|desc|description|subtitle|heading|placeholder|caption|tooltip|blurb)\b/.test(s))
    continue;
  for (const m of s.matchAll(/\b([a-zA-Z_$][\w$]*)\s*:\s*("(?:[^"\\]|\\.)*")/g)) {
    if (!DISPLAY.test(m[1])) continue;
    try {
      const v = JSON.parse(m[2]);
      if (v.trim().length > 1 && /[A-Za-z]{2}/.test(v)) used.add(v);
    } catch { /* ignore */ }
  }
}

// Every key in the dictionary. Parsed from the source text rather than
// imported, so this runs without a build step.
const dict = fs.readFileSync(path.join(SRC, 'i18n', 'id.ts'), 'utf8');
// Only the static block is checkable. ID_RUNTIME holds keys that arrive as
// data — API status enums, industry values — which never appear as a literal
// anywhere, so scanning for them would report every one as stale.
const staticBlock = dict.split('ID_RUNTIME')[0];
const keys = new Set();
for (const m of staticBlock.matchAll(/^\s*("(?:[^"\\]|\\.)*")\s*:/gm)) {
  try { keys.add(JSON.parse(m[1])); } catch { /* ignore */ }
}

const stale = [...keys].filter((k) => !used.has(k)).sort();
const missing = [...used].filter((k) => !keys.has(k)).sort();

console.log(`i18n: ${used.size} strings wrapped, ${keys.size} translated`);

if (stale.length) {
  console.log(`\n${stale.length} dictionary entr${stale.length === 1 ? 'y' : 'ies'} ` +
              `no longer match any string in the UI:`);
  for (const k of stale) console.log('  stale  ' + JSON.stringify(k));
  console.log('  → the wording changed. Update the key, or drop the entry.');
}

if (missing.length) {
  console.log(`\n${missing.length} string${missing.length === 1 ? '' : 's'} ` +
              `with no Indonesian (these render in English):`);
  for (const k of missing) console.log('  todo   ' + JSON.stringify(k));
}

if (!stale.length && !missing.length) console.log('\nnothing stale, nothing missing.');

process.exit(STRICT && stale.length ? 1 : 0);
