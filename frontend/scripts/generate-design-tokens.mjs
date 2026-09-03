import { readFile, readdir, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const sourcePath = `${projectRoot}/src/design/tokens.json`;
const outputPath = `${projectRoot}/src/design/tokens.css`;
const check = process.argv.includes("--check");

const tokens = JSON.parse(await readFile(sourcePath, "utf8"));

function kebab(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

const familyPrefixes = {
  color: "c",
  typography: "t",
  space: "sp",
  size: "sz",
  shape: "shp",
  shadow: "sh",
  motion: "mo",
  layer: "z",
};

const segmentPrefixes = {
  color: { palette: "p", surface: "s", text: "t", border: "b", accent: "a", state: "st", syntax: "syn", chart: "ch", shadow: "sh" },
  typography: { family: "f", size: "s", weight: "w", "line-height": "lh", tracking: "tr" },
  motion: { duration: "d", easing: "e" },
};

function variableName(path) {
  const [family, ...rest] = path;
  const segments = family === "size" && rest[0] === "scale" ? rest.slice(1) : rest;
  if (segmentPrefixes[family]?.[segments[0]]) segments[0] = segmentPrefixes[family][segments[0]];
  return `--kt-${familyPrefixes[family] ?? family}-${segments.join("-")}`;
}

function flatten(value, path = []) {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => flatten(item, [...path, String(index)]));
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => flatten(item, [...path, kebab(key)]));
  }
  return [[variableName(path), String(value)]];
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

const flattened = flatten(tokens);
const tokenMap = new Map(flattened);
const sourceFilesForTokens = (await sourceFiles(`${projectRoot}/src`)).filter((path) => {
  if (path === outputPath || path === sourcePath) return false;
  return [".css", ".ts", ".tsx"].includes(extname(path));
});
const sourceText = (await Promise.all(sourceFilesForTokens.map((path) => readFile(path, "utf8")))).join("\n");
const used = new Set([...sourceText.matchAll(/var\((--kt-[\w-]+)/g)].map((match) => match[1]));
for (const name of used) {
  const value = tokenMap.get(name);
  if (!value) continue;
  for (const dependency of value.matchAll(/var\((--kt-[\w-]+)/g)) used.add(dependency[1]);
}

const declarations = flattened
  .filter(([name]) => used.has(name))
  .map(([name, value]) => `  ${name}: ${value};`)
  .join("\n");
const generated = `/* Generated from tokens.json. Run npm run tokens:generate; do not edit by hand. */\n:root {\n${declarations}\n}\n`;

if (check) {
  const current = await readFile(outputPath, "utf8").catch(() => "");
  if (current !== generated) {
    console.error("Design tokens are stale. Run npm run tokens:generate.");
    process.exitCode = 1;
  }
} else {
  await writeFile(outputPath, generated, "utf8");
}
