import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}-{projectName}{ext}",
  reporter: [["list"]],
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { browserName: "webkit" } },
  ],
  globalTeardown: "./tests/e2e_teardown.ts",
  use: {
    baseURL: "http://127.0.0.1:8766",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "${KIRIN_PYTHON:-../.venv/bin/python} tests/e2e_server.py",
    url: "http://127.0.0.1:8766/",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
