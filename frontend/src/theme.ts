import { createTheme, Drawer, Menu, Modal, Popover, Tooltip } from "@mantine/core";
import type { MantineColorsTuple } from "@mantine/core";

import tokens from "./design/tokens.json";

const palette = tokens.color.palette;

function mantinePalette(values: string[]): MantineColorsTuple {
  if (values.length !== 10) throw new Error("Mantine palettes require exactly ten design-token stops.");
  return values as unknown as MantineColorsTuple;
}

export const kirinTheme = createTheme({
  primaryColor: "ember",
  primaryShade: 5,
  defaultRadius: tokens.shape.radius,
  cursorType: "pointer",
  autoContrast: true,
  luminanceThreshold: 0.42,
  fontFamily: tokens.typography.family.sans,
  fontFamilyMonospace: tokens.typography.family.mono,
  fontSizes: {
    xs: tokens.typography.size.meta,
    sm: tokens.typography.size.body,
    md: tokens.typography.size.label,
    lg: tokens.typography.size.titleSmall,
    xl: tokens.typography.size.titleMedium,
  },
  lineHeights: {
    xs: tokens.typography.lineHeight.compact,
    sm: tokens.typography.lineHeight.body,
    md: tokens.typography.lineHeight.body,
    lg: tokens.typography.lineHeight.relaxed,
    xl: tokens.typography.lineHeight.heading,
  },
  spacing: {
    xs: tokens.space["2"],
    sm: tokens.space["3"],
    md: tokens.space["4"],
    lg: tokens.space["5"],
    xl: tokens.space["6"],
  },
  radius: {
    xs: tokens.shape.radius,
    sm: tokens.shape.radius,
    md: tokens.shape.radius,
    lg: tokens.shape.radius,
    xl: tokens.shape.radius,
  },
  shadows: {
    xs: tokens.shadow.popover,
    sm: tokens.shadow.popover,
    md: tokens.shadow.menu,
    lg: tokens.shadow.notification,
    xl: tokens.shadow.dialog,
  },
  headings: {
    fontFamily: tokens.typography.family.sans,
    fontWeight: tokens.typography.weight.semibold,
    sizes: {
      h1: { fontSize: tokens.typography.size.titleLarge, lineHeight: tokens.typography.lineHeight.heading },
      h2: { fontSize: tokens.typography.size.titleSmall, lineHeight: tokens.typography.lineHeight.compact },
      h3: { fontSize: tokens.typography.size.label, lineHeight: tokens.typography.lineHeight.body },
    },
  },
  components: {
    Drawer: Drawer.extend({
      defaultProps: {
        closeButtonProps: { "aria-label": "关闭抽屉" },
        overlayProps: { zIndex: Number(tokens.layer.overlay) },
        zIndex: Number(tokens.layer.drawer),
      },
    }),
    Modal: Modal.extend({
      defaultProps: {
        closeButtonProps: { "aria-label": "关闭对话框" },
        overlayProps: { zIndex: Number(tokens.layer.overlay) },
        zIndex: Number(tokens.layer.modal),
      },
    }),
    Menu: Menu.extend({
      defaultProps: {
        zIndex: Number(tokens.layer.popover),
      },
    }),
    Popover: Popover.extend({
      defaultProps: {
        zIndex: Number(tokens.layer.popover),
      },
    }),
    Tooltip: Tooltip.extend({
      defaultProps: {
        multiline: true,
        openDelay: Number.parseInt(tokens.motion.duration.standard),
        zIndex: Number(tokens.layer.tooltip),
        transitionProps: {
          duration: Number.parseInt(tokens.motion.duration.fast),
          timingFunction: tokens.motion.easing.standard,
        },
      },
    }),
  },
  colors: {
    dark: mantinePalette(palette.dark),
    ember: mantinePalette(palette.ember),
    gray: mantinePalette(palette.gray),
    orange: mantinePalette(palette.orange),
    green: mantinePalette(palette.green),
    red: mantinePalette(palette.red),
  },
  other: {
    borderColor: tokens.color.border.default,
    panelColor: tokens.color.surface.panel,
    workspaceColor: tokens.color.surface.workspace,
  },
});
