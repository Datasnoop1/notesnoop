# Ownership graph prod flip evidence - 2026-05-02

Branch: `feat/ownership-graph-prod-flip`

## Scope

Flip `OWNERSHIP_GRAPH_READ_ENABLED=true` in production so
`/api/companies/<cbe>/structure` reads shareholders, participating interests,
and parent companies from `ownership_edge_current`.

Rollback remains a single env-file flip back to `false` plus backend recreate.

## Pre-flip checks

Production flag state before the gated step:

```text
ownership_flag_present: false
ownership_flag_true: false
```

Direct SQL sample discovery found these live two-hop ownership chains in
`ownership_edge_current`:

```text
0437312028 CEFRAB -> 0436757247 DEBRIMMO -> 0839525694 De Brauwer Vastgoed
0476943753 BIK KNOKKE -> 0456815164 DE BACKER AFDICHTINGEN - KNOKKE -> 0641635303 LNY
0443891695 AMC -> 0428435538 DEJAGER TRANS -> 0887330858 CERIMA
0431404530 SUNPARKS LEISURE -> 0432515872 Center Parcs Ardennen -> 0434692830 CPSP Belgie
```

## Prod gate

Pending. The gated step must:

1. Set `OWNERSHIP_GRAPH_READ_ENABLED=true` in
   `/opt/leadpeek/.env.production` without printing any secrets.
2. Recreate the production backend with `--force-recreate`.
3. Smoke `/api/companies/<cbe>/structure` and `/api/companies/<cbe>/ownership-graph`
   for 3-5 sample companies.
4. Verify the graph-backed read path returns immediate parents in
   `/structure` and multi-hop chains in `ownership-graph.ubo_walk`.
