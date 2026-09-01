import { readdir, stat } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve("dist");
const files = await readdir(dist);
const sizes = new Map();
for (const file of files) {
  const info = await stat(resolve(dist, file));
  if (info.isFile()) sizes.set(file, info.size);
}

const javascript = [...sizes].filter(([file]) => file.endsWith(".js"));
const css = [...sizes].filter(([file]) => file.endsWith(".css"));
const entry = javascript.find(([file]) => file.startsWith("index-"));
const totalJavaScript = javascript.reduce((total, [, size]) => total + size, 0);
const largestChunk = javascript.reduce((largest, item) => item[1] > (largest?.[1] ?? 0) ? item : largest, null);
const totalCss = css.reduce((total, [, size]) => total + size, 0);

const budgets = [
  ["initial JavaScript", entry?.[1] ?? Infinity, 650_000],
  ["largest JavaScript chunk", largestChunk?.[1] ?? Infinity, 700_000],
  ["total JavaScript", totalJavaScript, 2_400_000],
  ["total CSS", totalCss, 300_000],
];

let failed = false;
for (const [label, size, limit] of budgets) {
  const ok = size <= limit;
  process.stdout.write(`${ok ? "PASS" : "FAIL"} ${label}: ${size.toLocaleString()} / ${limit.toLocaleString()} bytes\n`);
  failed ||= !ok;
}
if (largestChunk) process.stdout.write(`Largest chunk: ${largestChunk[0]}\n`);
if (failed) process.exitCode = 1;
