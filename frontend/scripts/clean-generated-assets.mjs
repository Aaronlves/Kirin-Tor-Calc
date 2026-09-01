import { readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve("dist");
for (const file of await readdir(dist)) {
  if (!file.endsWith(".js") && !file.endsWith(".css") && !file.endsWith(".html")) continue;
  const path = resolve(dist, file);
  const source = await readFile(path, "utf8");
  const cleaned = source.replace(/^[\t ]+$/gm, "");
  if (cleaned !== source) await writeFile(path, cleaned, "utf8");
}
