import { readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { cssTokenDependencies, directTokenLeaves, expectedFamilies, flattenTokens, sourceFiles } from "./design-token-contract.mjs";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const sourceRoot = join(projectRoot, "src");
const tokenPath = join(sourceRoot, "design", "tokens.json");
const generatedPath = join(sourceRoot, "design", "tokens.css");
const tokens = JSON.parse(await readFile(tokenPath, "utf8"));
const failures = [];

if (JSON.stringify(Object.keys(tokens)) !== JSON.stringify(expectedFamilies)) {
  failures.push(`tokens.json must contain exactly these ordered families: ${expectedFamilies.join(", ")}`);
}

const files = (await sourceFiles(sourceRoot)).filter((path) => {
  if (path === generatedPath || path === tokenPath) return false;
  return [".css", ".ts", ".tsx"].includes(extname(path));
});
const generated = await readFile(generatedPath, "utf8");
const declarations = new Set([...generated.matchAll(/(--kt-[\w-]+)\s*:/g)].map((match) => match[1]));
const sourceByPath = new Map(await Promise.all(files.map(async (path) => [path, await readFile(path, "utf8")])));
const sourceText = [...sourceByPath.values()].join("\n");
const flattened = flattenTokens(tokens);
const directlyUsed = directTokenLeaves(sourceText, flattened);
const cssUsed = cssTokenDependencies(sourceText, flattened, directlyUsed);
const styles = sourceByPath.get(join(sourceRoot, "styles.css")) ?? "";
const responsiveThresholds = new Set([...styles.matchAll(/@(?:media|container)[^{]*\(max-width:\s*(\d+px)\)/g)].map((match) => match[1]));
const sizeScaleValues = new Set(Object.values(tokens.size.scale));

for (const threshold of responsiveThresholds) {
  if (!sizeScaleValues.has(threshold)) failures.push(`styles.css uses unregistered responsive threshold ${threshold}`);
}

const unusedTokens = flattened.filter((token) => {
  const responsiveUse = token.path[0] === "size" && token.path[1] === "scale" && responsiveThresholds.has(token.value);
  return !cssUsed.has(token.name) && !directlyUsed.has(token.name) && !responsiveUse;
});
if (unusedTokens.length) {
  failures.push(`tokens.json contains unused values: ${unusedTokens.map((token) => token.path.join(".")).join(", ")}`);
}

for (const path of files) {
  const source = sourceByPath.get(path);
  const name = relative(projectRoot, path);
  source.split("\n").forEach((line, index) => {
    if (/#[\da-f]{3,8}\b|rgba?\(/i.test(line)) failures.push(`${name}:${index + 1} contains a raw color`);
    if (/\b(?:font-size|font-weight|line-height|letter-spacing|border-radius|box-shadow|z-index)\s*:\s*-?[\d.]/.test(line)) {
      failures.push(`${name}:${index + 1} bypasses its design-token family`);
    }
    if (/\btransition(?:-[\w-]+)?\s*:[^;]*(?:\d+ms|cubic-bezier\(|\bease\b)/.test(line)) {
      failures.push(`${name}:${index + 1} contains raw motion values`);
    }
    const responsiveMatch = line.match(/^\s*@(media|container)[^{]*\(max-width: (\d+px)\)/);
    if (/\d+px\b/.test(line) && !(responsiveMatch && sizeScaleValues.has(responsiveMatch[2]))) {
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

if (!styles.includes("@media (prefers-reduced-motion: reduce)")) {
  failures.push("styles.css must provide a reduced-motion override");
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`PASS design system: ${expectedFamilies.length} families, ${flattened.length} live values, ${declarations.size} generated variables, no unmanaged or unused tokens`);
}
