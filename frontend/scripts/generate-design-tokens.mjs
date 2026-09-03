import { readFile, writeFile } from "node:fs/promises";
import { extname } from "node:path";
import { fileURLToPath } from "node:url";

import { cssTokenDependencies, directTokenLeaves, flattenTokens, sourceFiles } from "./design-token-contract.mjs";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const sourcePath = `${projectRoot}/src/design/tokens.json`;
const outputPath = `${projectRoot}/src/design/tokens.css`;
const check = process.argv.includes("--check");

const tokens = JSON.parse(await readFile(sourcePath, "utf8"));

const flattened = flattenTokens(tokens);
const sourceFilesForTokens = (await sourceFiles(`${projectRoot}/src`)).filter((path) => {
  if (path === outputPath || path === sourcePath) return false;
  return [".css", ".ts", ".tsx"].includes(extname(path));
});
const sourceText = (await Promise.all(sourceFilesForTokens.map((path) => readFile(path, "utf8")))).join("\n");
const directlyUsed = directTokenLeaves(sourceText, flattened);
const used = cssTokenDependencies(sourceText, flattened, directlyUsed);

const declarations = flattened
  .filter(({ name }) => used.has(name))
  .map(({ name, value }) => `  ${name}: ${value};`)
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
