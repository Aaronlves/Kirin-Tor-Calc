import { readFile, readdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const sourceRoot = join(projectRoot, "src");
const tokenPath = join(sourceRoot, "design", "tokens.json");
const generatedPath = join(sourceRoot, "design", "tokens.css");
const expectedFamilies = ["color", "typography", "space", "size", "shape", "shadow", "motion", "layer"];
const tokens = JSON.parse(await readFile(tokenPath, "utf8"));
const failures = [];

if (JSON.stringify(Object.keys(tokens)) !== JSON.stringify(expectedFamilies)) {
  failures.push(`tokens.json must contain exactly these ordered families: ${expectedFamilies.join(", ")}`);
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [path];
  }));
  return nested.flat();
}

const files = (await sourceFiles(sourceRoot)).filter((path) => {
  if (path === generatedPath || path === tokenPath) return false;
  return [".css", ".ts", ".tsx"].includes(extname(path));
});
const generated = await readFile(generatedPath, "utf8");
const declarations = new Set([...generated.matchAll(/(--kt-[\w-]+)\s*:/g)].map((match) => match[1]));

for (const path of files) {
  const source = await readFile(path, "utf8");
  const name = relative(projectRoot, path);
  source.split("\n").forEach((line, index) => {
    if (/#[\da-f]{3,8}\b|rgba?\(/i.test(line)) failures.push(`${name}:${index + 1} contains a raw color`);
    if (/\b(?:font-size|font-weight|line-height|letter-spacing|border-radius|box-shadow|z-index)\s*:\s*-?[\d.]/.test(line)) {
      failures.push(`${name}:${index + 1} bypasses its design-token family`);
    }
    if (/\btransition(?:-[\w-]+)?\s*:[^;]*(?:\d+ms|cubic-bezier\(|\bease\b)/.test(line)) {
      failures.push(`${name}:${index + 1} contains raw motion values`);
    }
    if (/\d+px\b/.test(line) && !/^\s*@media \(max-width: (?:1320|1180)px\)/.test(line)) {
      failures.push(`${name}:${index + 1} contains a raw pixel value`);
    }
  });
  for (const match of source.matchAll(/var\((--kt-[\w-]+)/g)) {
    if (!declarations.has(match[1])) failures.push(`${name} references unknown token ${match[1]}`);
  }
  for (const match of source.matchAll(/<(?:a|button|div|input|select|span|textarea)\b[^>]*\btitle\s*=/gs)) {
    const line = source.slice(0, match.index).split("\n").length;
    failures.push(`${name}:${line} uses a native title tooltip; use the shared Tooltip system`);
  }
}

const styles = await readFile(join(sourceRoot, "styles.css"), "utf8");
if (!styles.includes("@media (prefers-reduced-motion: reduce)")) {
  failures.push("styles.css must provide a reduced-motion override");
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`PASS design system: ${expectedFamilies.length} token families, ${declarations.size} generated variables, no unmanaged visual literals`);
}
