import { rm } from "node:fs/promises";
import { resolve } from "node:path";

export default async function teardown() {
  await rm(resolve(".e2e-workspace"), { recursive: true, force: true });
  await rm(resolve(".e2e-workspace-other"), { recursive: true, force: true });
}
