# Batch A security assessment (manual) — 2026-04-24

Primary delegated security review timed out on both Ollama + NVIDIA providers. A retry is in flight; this is the operator-safe manual assessment in parallel, covering the same surface.

## Changes reviewed

1. `company-page-client.tsx` — BTW copy button (navigator.clipboard.writeText), legal-form display
2. `bs-bridge.tsx` — palette classes + optional text color
3. `favourites/page.tsx` — replaced inline popover with Dialog overlay
4. `network-graph.tsx` — client-side layer visibility filter + Tier 1 palette/label/hub-weight tweaks
5. `company/[cbe]/layout.tsx` — canonical + OG URL metadata
6. `sitemap.ts` — added API_URL_INTERNAL env fallback + console.error on failure
7. i18n JSON additions

## Findings

**No material findings.** Specifically:

- **XSS:** `detail.jf_label` and all other interpolated fields are rendered via JSX `{...}`, so React auto-escapes. No `dangerouslySetInnerHTML` introduced or nearby.
- **Clipboard:** Writing the bare CBE number (public data). `navigator.clipboard.writeText` requires HTTPS; prod is HTTPS, staging can warn but doesn't expose sensitive data. Rejected-promise path is a no-op; no leaks.
- **Dialog:** `@/components/ui/dialog` is a base-ui DialogPrimitive wrapper that includes a Portal, Backdrop, focus trap, and Escape/overlay-click close. Correctly used — no clickjacking exposure beyond the existing site surface.
- **Layer toggle state:** Pure client filter on `data.edges`/`data.nodes`; no new API calls, no user input reflected. The role classification is a substring match on a server-supplied string — rendered into classnames via a constant path, not string concatenation into markup.
- **Canonical URL:** Hard-coded `https://datasnoop.be` prefix. The `cleanCbe` value is derived server-side from the route param via `cbe.replace(/\./g, "").padStart(10, "0")` — not attacker-controllable in a meaningful way, and the canonical tag output is a plain URL attribute, not HTML.
- **Sitemap logs:** `console.error` writes to server stderr — contained in the container. The logged strings contain `API_BASE` (internal) and the HTTP status; no secrets.
- **i18n strings:** Static JSON content; no data interpolation risk.

## Verdict

Safe to merge. Retry of the delegated review will update this file if anything material turns up; until then, green-light.
