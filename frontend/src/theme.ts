import { createTheme, rem } from "@mantine/core";

export const kirinTheme = createTheme({
  primaryColor: "ember",
  primaryShade: 5,
  defaultRadius: 0,
  cursorType: "pointer",
  autoContrast: true,
  luminanceThreshold: 0.42,
  fontFamily:
    "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Noto Sans CJK SC', sans-serif",
  fontFamilyMonospace:
    "'SFMono-Regular', Menlo, Consolas, 'Noto Sans Mono CJK SC', monospace",
  headings: {
    fontFamily:
      "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Noto Sans CJK SC', sans-serif",
    fontWeight: "650",
    sizes: {
      h1: { fontSize: rem(23), lineHeight: "1.2" },
      h2: { fontSize: rem(16), lineHeight: "1.35" },
      h3: { fontSize: rem(14), lineHeight: "1.4" },
    },
  },
  colors: {
    dark: [
      "#eceee9", "#d6d9d2", "#b5b9b0", "#858a81", "#62675f",
      "#4b4f48", "#3c3f38", "#292b27", "#191a17", "#0e0f0d"
    ],
    ember: [
      "#fff1eb", "#f9d9cd", "#efb8a3", "#e29478", "#d98061",
      "#cf7455", "#b85e42", "#984a35", "#7a3c2e", "#633329"
    ],
    gray: [
      "#f1f2ef", "#dcdfd9", "#c3c7bf", "#a7aca3", "#8b9188",
      "#71766e", "#585d56", "#41453f", "#292b27", "#171815"
    ],
    orange: [
      "#fff4e8", "#f6dfc2", "#eac796", "#dbae6a", "#cc994d",
      "#c18a40", "#aa7332", "#8a5a29", "#6f4824", "#5a3c21"
    ],
    green: [
      "#eff7eb", "#d6e7ce", "#b8d3aa", "#9bbc89", "#86a873",
      "#72965f", "#5c7e4c", "#48643d", "#394f32", "#2d4029"
    ],
    red: [
      "#fcecec", "#f3d0d0", "#e5aaaa", "#d88787", "#cf7070",
      "#c45d5d", "#ad4949", "#8e3a3a", "#742f2f", "#602929"
    ],
  },
  other: {
    borderColor: "#292b27",
    panelColor: "#141512",
    workspaceColor: "#0e0f0d",
  },
});
