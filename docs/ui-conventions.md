# DataSnoop — UI Conventions

Canonical UI rulebook for the Next.js 16 + Tailwind v4 frontend. This
captures what was previously scattered across `architecture.md` prose,
inline comments, and implicit habits. Read this before editing any
page; update it when a convention changes.

---

## Breakpoints

Tailwind defaults:

- `sm:` = 640px
- `md:` = 768px  ← **mobile-phone cutoff**
- `lg:` = 1024px
- `xl:` = 1280px
- `2xl:` = 1536px (matches `max-w-[1536px]` layout wrapper)

**Mobile-first rule.** Write `h-10 md:h-7` (mobile default, shrinks on
md+), never `h-7 md:h-10`. The convention for the whole repo is
`md:` as the phone/tablet transition — not `sm:`. A 640–767px screen
is still phone territory.

**Test breakpoints** when eyeballing a change:

| Width | Why |
|---|---|
| 375px | iPhone SE, smallest modern phone |
| 414px | iPhone 14/15 Pro Max portrait |
| 768px | iPad portrait — the `md:` boundary |
| 1024px | iPad landscape / small laptop |
| 1280px | Laptop default |
| 1536px | Max layout width — past this, content re-centers |

---

## Input sizing (iOS zoom)

Safari on iOS zooms the viewport when a focused input's computed
font-size is less than 16px. The repo's html base is `font-size: 14px`
(globals.css), which means Tailwind's `text-base` = 14px — technically
still under the threshold, so a strict iOS Safari build could still
trigger zoom. No regressions have been reported with the `text-base`
convention in practice, so we use it as the "as safe as the repo gets
without re-scaling every element" rule. If a future iOS release makes
the zoom stricter, the escape hatch is either `text-[16px]` on the
offending input or bumping html base back to 16px (the latter
re-scales the whole app — not done lightly).

**Canonical input pattern:**

```tsx
<Input className="h-10 md:h-7 text-base md:text-xs" />
```

- Mobile: 40px tall, `text-base` (14px) — tap-friendly, ~no zoom.
- md+: 28px tall, `text-xs` (10.5px) — dense admin-style.

Use the same pattern on raw `<input>`, `<select>`, `<textarea>`.
Don't use `h-7`, `h-8`, `text-xs`, `text-sm` without a `md:` guard —
that's the iOS-zoom trap and the sub-44px tap-target trap.

---

## Tap targets

Apple HIG floor: **44px** for primary actions. The repo accepts:

- 44px (`h-11` or `min-h-[44px]`) for primary CTAs and icon-only buttons
  that are the only affordance in a row.
- 40px (`h-10`) for secondary buttons and inline row actions.
- 32–36px (`h-8`–`h-9`) for tertiary controls inside dense admin
  tables — on mobile use `h-10 md:h-8` instead of `h-8` flat.

Never ship icon-only buttons smaller than 44px on mobile without a
text label or a larger hit area (`p-2.5 -m-2.5` etc).

---

## Scroll affordance on mobile

**Never** use `scrollbar-none` on a container that is actually
scrollable on mobile — it hides the only visual cue that the content
scrolls. Gate it with `md:scrollbar-none` so desktop gets the clean
look and mobile keeps the native scrollbar.

The utility is defined in `globals.css` via Tailwind v4 `@utility` and
supports all variants (`md:scrollbar-none`, `hover:scrollbar-none`,
etc).

For wide tables, two tools:

1. **Hide low-priority columns on mobile**: `<TableHead className="hidden md:table-cell">`.
   Apply on both `<TableHead>` and the matching `<TableCell>`.
   Don't change `colSpan` — hidden cells still count structurally.
2. **Sticky first column** on financial tables. Canonical pattern:
   ```tsx
   className="sticky left-0 z-[5] bg-white
              shadow-[1px_0_0_rgba(226,232,240,1)]
              w-[110px] md:w-auto md:min-w-[240px]
              whitespace-normal break-words"
   ```
   Use for P&L / cash flow / balance sheet / credit / valuation / compare
   / aggregate. Users can scroll the numeric columns horizontally
   while the label stays pinned.

---

## Typography

Canonical scale (defined in `globals.css` → `@layer components`):

| Class | Purpose | Mobile | md+ |
|---|---|---|---|
| `.heading-1` | Page title | 24px semibold | 30px semibold |
| `.heading-2` | Section title | 20px semibold | 24px semibold |
| `.heading-3` | Subsection | 18px medium | 20px medium |
| `.heading-4` | Card title | 14px medium | 18px medium |
| `.section-label` | "PEOPLE & ROLES" caps label | 12px bold uppercase | same |
| `.body-lg` | Intro paragraph | 14px | 18px |
| `.body` | Normal paragraph | 12px | 14px |
| `.body-sm` | Caption / help text | 10.5px | 12px |

Prefer these over ad-hoc `text-[Npx]` sizes. Existing pages using
`text-[10/11/13px]` are grandfathered in — only replace when
touching that code for other reasons.

**Fonts.** Geist is the default. Users can opt into Inter or DM Sans
via `/account` → font picker; persisted in `localStorage` and applied
at runtime by `FontProvider`. All three are loaded by `layout.tsx` —
don't remove any without also removing the picker.

---

## Colour

Two layers:

1. **Shadcn tokens** (defined as OKLch CSS variables in
   `globals.css`): `bg-background`, `text-foreground`, `bg-card`,
   `border-border`, `bg-muted`, `text-muted-foreground`, `bg-accent`,
   `text-destructive`, etc. Used by the shadcn primitives in
   `components/ui/`.
2. **Brand accent** (new, 2026-04-18): `bg-brand`, `text-brand`,
   `bg-brand-soft`. Soft indigo (~`#4d5fd0`). Use for new primary
   buttons, accent highlights, subtle brand surfaces.

**Existing pages hardcode Tailwind colours** (`text-slate-600`,
`bg-indigo-100`, `text-rose-500`, `text-emerald-600`, etc). That is
known drift — the tokens were under-utilised for the first year of
the project. **Do not mass-migrate.** When adding new surfaces,
prefer tokens. When refactoring, migrate incrementally with a visual
check on staging.

**Dark mode is not a product feature.** The `.dark {}` block in
`globals.css` is legacy scaffolding from the shadcn template; nothing
wires it up, and it will not ship. Don't add `dark:` variants to new
code.

---

## Spacing

Stick to the 4/8 scale: `gap-2/4/6/8`, `space-y-4/6/8`,
`p-2/3/4/6/8`. `gap-1.5`, `gap-2.5`, `gap-3.5` are legal when the
design specifically calls for it, but avoid as defaults.

Global container: `max-w-[1536px] mx-auto px-4 sm:px-6 lg:px-8` —
lives in `layout.tsx`, every page inherits. Narrower inner
containers (`max-w-[1200px]` / `max-w-xl`) set their own
`mx-auto w-full`.

Exception: **screener** is full-viewport split-pane, no max-width.

---

## Shared primitives — prefer over inline divs

When adding new UI, use these instead of rebuilding from scratch:

| Need | Component | Location |
|---|---|---|
| Clickable primary/secondary | `<Button>` | `components/ui/button.tsx` |
| Form input | `<Input>` / `<Textarea>` | `components/ui/input.tsx` |
| Container card | `<Card>` + `CardHeader/Title/Content` | `components/ui/card.tsx` |
| Modal | `<Dialog>` | `components/ui/dialog.tsx` |
| Mobile drawer | `<Sheet>` | `components/ui/sheet.tsx` |
| Tabs | `<Tabs>` | `components/ui/tabs.tsx` |
| Data grid | `<Table>` | `components/ui/table.tsx` |
| Status pill | `<Badge>` | `components/ui/badge.tsx` |
| Hover / click tip | `FormulaTooltip` (click-open + hover) | `company/[cbe]/helpers.tsx` |
| Kebab / context menu | `<DropdownMenu>` | `components/ui/dropdown-menu.tsx` |
| "Nothing here" state | `<EmptyState>` | `components/ui/empty-state.tsx` (new) |
| Loading placeholder | `<Skeleton>` | `components/ui/skeleton.tsx` (new) |

Many older pages (admin, favourites, compare) build tables and cards
inline with divs. Known drift — see the colour paragraph above. Not
a blocker to merging new code.

---

## Accessibility

Focus rings are defined on all shared primitives — don't strip them.
Keep `aria-label` on icon-only buttons. For tooltips / popovers that
reveal essential info (formulas, legends), use `FormulaTooltip`-style
click-open; never hover-only, because that silently breaks on touch
devices.

Keyboard: `Tab` should reach every interactive element. `Enter` +
`Space` activate buttons; `Esc` closes dialogs/popovers.

---

## Print

Print styles live at the bottom of `globals.css`, gated by
`@media print`. They hide `nav`, `footer`, ads, overlays, and shrink
valuation tab tables onto a single A4 page. Test with browser
`Ctrl-P` after touching any valuation tab layout.
