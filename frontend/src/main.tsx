import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/spotlight/styles.css";
import "./design/tokens.css";
import "./styles.css";

import { App } from "./App";
import { kirinTheme } from "./theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="dark" theme={kirinTheme}>
      <App />
    </MantineProvider>
  </StrictMode>,
);
