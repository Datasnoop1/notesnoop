# Spiderweb (network graph) legibility investigation — 2026-04-24

## Current state

- File: `frontend/src/components/network-graph.tsx` (~485 lines)
- Library: `react-force-graph-2d` (canvas, D3 force simulation)
- Layout: force-directed, charge `-200`, link distance `120px`, velocity decay `0.3`
- Colour: depth-based indigo gradient + relation-type edge colours (green shareholders, orange subsidiaries)
- Interaction: click-recenter, depth selector (1–4), fullscreen, zoom-to-fit
- Typical complex company: 50–200 nodes / 80–400 edges

## Pain points (ranked)

1. **Label overlap / crowding** (HIGH) — labels stack at depth 2–3 with 100+ nodes
2. **Edge-crossing spaghetti** (HIGH) — force layout alone doesn't minimise crossings
3. **No role-based visual hierarchy** (MEDIUM) — same indigo palette for shareholders/directors/subsidiaries; majors indistinguishable from minors
4. **Pale depth-3/4 colours** (MEDIUM) — `#a5b4fc` and `#c7d2fe` fade into white canvas
5. **No layer toggle** (MEDIUM-HIGH) — feature #20; forces operators to read everything at once

## Improvement backlog (effort · impact)

### Tier 1 — quick wins (S, 2–3 hours total)

1. Increase label font-size floor — `network-graph.tsx:417,462` (2 lines)
2. Saturate depth-3/4 node colours — `network-graph.tsx:48-54` (2 lines)
3. Weight node size by in-degree so hubs pop — `network-graph.tsx:226` (5 lines)
4. Animate dashes on ended-mandate edges — `network-graph.tsx:384-406` (1 line)

### Tier 2 — medium (M)

5. **Layer toggle for node types (#20) — TRIVIAL**, ~25 lines. Backend already sends `type` on every node. Frontend adds `useState({companies, people, subsidiaries})` + filter + three toggle buttons reusing depth-button UI.
6. Collision-avoidant label placement (offset to cardinal directions on overlap) — ~30 lines
7. Smart abbreviation at small zoom — ~10 lines

### Tier 3 — larger (L)

8. Hierarchical layout swap (dagre-based) for ownership trees — library add
9. Density-adaptive + focus mode (hide distant nodes, outline mode >150 nodes)
10. Community-detection colouring to isolate shareholding silos

## Phase 1 recommendation

Ship Tier 1 items 1–4 + item 5 (layer toggle) as one PR. 5–7 hours total. Delivers both #20 and #21 Tier-1 wins in a single round-trip.
