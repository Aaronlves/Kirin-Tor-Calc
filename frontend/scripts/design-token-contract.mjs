import { readdir } from "node:fs/promises";
import { join } from "node:path";

export const expectedFamilies = ["color", "typography", "space", "size", "shape", "shadow", "motion", "layer"];

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

function kebab(value) {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}

function variableName(path) {
  const [family, ...restFromPath] = path;
  const rest = family === "size" && restFromPath[0] === "scale" ? restFromPath.slice(1) : [...restFromPath];
  if (segmentPrefixes[family]?.[rest[0]]) rest[0] = segmentPrefixes[family][rest[0]];
  return `--kt-${familyPrefixes[family] ?? family}-${rest.join("-")}`;
}

export function flattenTokens(value, path = []) {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => flattenTokens(item, [...path, String(index)]));
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => flattenTokens(item, [...path, kebab(key)]));
  }
  return [{ name: variableName(path), path, value: String(value) }];
}

export async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  }));
  return nested.flat();
}

export function directTokenLeaves(source, flattened) {
  const identifiers = new Set([...source.matchAll(/import\s+([A-Za-z_$][\w$]*)\s+from\s+["'][^"']*design\/tokens\.json["']/g)]
    .map((match) => match[1]));
  const accesses = [...identifiers].flatMap((identifier) => {
    const expression = new RegExp(`(?<![\\w$])${identifier}((?:\\.[A-Za-z_$][\\w$]*|\\[(?:"[^"]+"|'[^']+'|\\d+)\\])+)`, "g");
    return [...source.matchAll(expression)].map((match) => [...match[1].matchAll(/\.([A-Za-z_$][\w$]*)|\[(?:"([^"]+)"|'([^']+)'|(\d+))\]/g)]
      .map((segment) => kebab(segment[1] ?? segment[2] ?? segment[3] ?? segment[4])));
  });

  return new Set(flattened
    .filter((token) => accesses.some((access) => access.length <= token.path.length
      && access.every((segment, index) => segment === token.path[index])))
    .map((token) => token.name));
}

export function cssTokenDependencies(source, flattened, directLeaves = new Set()) {
  const byName = new Map(flattened.map((token) => [token.name, token]));
  const used = new Set([...source.matchAll(/var\((--kt-[\w-]+)/g)].map((match) => match[1]));
  const pending = [...new Set([...used, ...directLeaves])];

  for (let index = 0; index < pending.length; index += 1) {
    const token = byName.get(pending[index]);
    if (!token) continue;
    for (const match of token.value.matchAll(/var\((--kt-[\w-]+)/g)) {
      if (!used.has(match[1])) {
        used.add(match[1]);
        pending.push(match[1]);
      }
    }
  }
  return used;
}
