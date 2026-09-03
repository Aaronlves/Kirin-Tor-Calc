# Kirin Tor Workbench design system

The browser workbench has one visual authority: `frontend/src/design/tokens.json`. It contains exactly eight token families. `npm run tokens:generate` turns that source into `frontend/src/design/tokens.css`; the generated file is checked in so the first rendered frame and packaged runtime use the same values. It must not be edited by hand.

| Family | Owns | Does not own |
| --- | --- | --- |
| `color` | palettes and semantic surface, text, border, accent, state, syntax, chart, and shadow colors | spacing, opacity used as interaction state, or data values |
| `typography` | sans/mono families, type scale, weights, line heights, and tracking | box dimensions or icon geometry |
| `space` | the shared spacing scale used by gap, padding, and margin | component height and layout width |
| `size` | primitive dimensions plus semantic control, toolbar, navigation, chart, reading-width, and editor dimensions | spacing between elements |
| `shape` | radius, border thickness, and focus-ring offsets | border color or elevation |
| `shadow` | focus, active, popover, menu, notification, dialog, and backdrop treatments | the colors used by those treatments, which remain in `color` |
| `motion` | durations and easing curves | state changes or calculation progress semantics |
| `layer` | named stacking levels | DOM order or document authority |

The JSON source has two levels. Primitive palettes and scales make the available vocabulary finite; semantic roles such as `color.surface.panel`, `typography.size.meta`, and `size.control` state why a value is used. New components consume semantic roles where one exists. A new primitive is justified only when no existing scale value can express the requirement. Every leaf value must have a current consumer in CSS, a renderer adapter, or a registered responsive threshold; speculative and compatibility-only tokens are rejected rather than retained for possible future use.

## Renderer adapters

- Mantine receives its palettes, font families, type sizes, line heights, spacing, radii, and shadows from the JSON source in `frontend/src/theme.ts`; `frontend/src/mantine.css` retains Mantine's baseline and default geometry variables, then imports only the component styles the workbench renders. The default variable sheet is a renderer contract, not a second visual authority.
- Ordinary component styling consumes generated `--kt-*` custom properties in `frontend/src/styles.css`.
- CodeMirror consumes the same custom properties for editor typography, syntax roles, selection, focus, shape, elevation, and its localized find/replace controls.
- ECharts receives concrete canvas values from the same JSON source through the registered `kirin-tor` theme. Chart-specific option objects may choose layout and interaction behavior, but cannot create another palette or type scale.

The design system changes presentation only. It does not create state, modify `.kirin`, or allow Workbench Plugins to override host authority. Plugin iframe contents remain responsible for their own internal styling; their host frame and management surfaces use the Kirin system.

## Motion and accessibility

Motion is productive rather than decorative. Color and surface transitions use the fast duration; the standard duration is reserved for current interaction timing. Data values must not tween in a way that implies recalculation. Under `prefers-reduced-motion: reduce`, host transitions become instant. Pointer-only presentation must retain a keyboard-readable or keyboard-operable equivalent.

Focus rings use the shared shape, color, shadow, and layer tokens. CodeMirror's drawn selection occupies the named selection layer above opaque line surfaces and below focus controls, so focused and unfocused selections remain visibly distinct. Its isolated editor stacking context contains a pointer-transparent focus frame above CodeMirror's gutters, panels, and active-line surfaces, keeping all four edges continuous without escaping above application overlays. Text and state colors remain semantic roles rather than component-local literals. Passing automated accessibility checks is implementation evidence, not human visual acceptance.

Application floating surfaces use one named layer ladder: the application header remains below the
overlay boundary; Drawer, Modal, Spotlight, Popover/Menu, Tooltip, and Notification each receive
their runtime `z-index` from `tokens.json`. Editor tooltip and focus values are local to CodeMirror's
isolated stacking context. A workspace tool owns one modal Drawer; drill-in forms, confirmations,
author tools, and community discovery replace its body with an explicitly labelled subview instead
of opening a second modal Drawer. This keeps modal depth at one while preserving an explicit back
path and the parent tool's state.

Host tooltips use one rectangular floating surface, border, shadow, type scale, wrapping rule, and pointer-transparent interaction model. Mantine tooltips remain viewport-aware, every CodeMirror tooltip is confined to the editor rectangle, and ECharts tooltips are confined to an isolated chart canvas. Native HTML `title` tooltips are rejected because they bypass these rules; iframe `title` remains an accessibility name rather than a visual tooltip. Plugin iframe contents remain outside the host styling boundary.

## Enforcement and workflow

The production build runs both token gates before TypeScript and Vite:

```bash
cd frontend
npm run tokens:generate  # only after editing tokens.json
npm run tokens:check     # generated CSS is current
npm run design:check     # eight families, resolved references, no unmanaged literals
npm run build
```

`design:check` rejects raw colors, pixel dimensions, typography values, shadows, stacking values, motion constants, and unused token leaves. Responsive media-query thresholds remain literal in CSS because custom properties are not resolved in media-query conditions, but each literal must match a registered `size.scale` value; application-side queries import the same source value.
