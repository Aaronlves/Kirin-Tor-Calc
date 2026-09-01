import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/assets/",
  plugins: [react()],
  build: {
    assetsDir: ".",
    emptyOutDir: true,
    manifest: true,
    outDir: "dist",
  },
});
