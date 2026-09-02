import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/spotlight/styles.css";
import "./styles.css";

import { App } from "./App";
import { kirinTheme } from "./theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="dark" theme={kirinTheme}>
      <Notifications position="top-right" autoClose={4000} limit={3} />
      <App />
    </MantineProvider>
  </StrictMode>,
);
