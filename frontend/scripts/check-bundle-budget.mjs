import { readdirSync, readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const assetDir = new URL('../dist/assets/', import.meta.url);
const assets = readdirSync(assetDir).filter((name) => /\.(?:js|css)$/.test(name));
const sizes = assets.map((name) => ({
  name,
  bytes: gzipSync(readFileSync(new URL(name, assetDir))).byteLength,
}));
const js = sizes.filter(({ name }) => name.endsWith('.js'));
const css = sizes.filter(({ name }) => name.endsWith('.css'));
const failures = [];
const largestJs = Math.max(0, ...js.map(({ bytes }) => bytes));
const largestCss = Math.max(0, ...css.map(({ bytes }) => bytes));
const totalJs = js.reduce((sum, { bytes }) => sum + bytes, 0);

if (largestJs > 350_000) failures.push(`largest JavaScript chunk ${largestJs} > 350000 gzip bytes`);
if (largestCss > 80_000) failures.push(`largest CSS asset ${largestCss} > 80000 gzip bytes`);
if (totalJs > 900_000) failures.push(`total JavaScript ${totalJs} > 900000 gzip bytes`);
if (failures.length) throw new Error(`Bundle budget exceeded:\n${failures.join('\n')}`);
console.log(`Bundle budget: largest JS ${largestJs}, largest CSS ${largestCss}, total JS ${totalJs} gzip bytes`);
