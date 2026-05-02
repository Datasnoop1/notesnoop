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

Gate Y comment: PR #45 comment
`https://github.com/Datasnoop1/platform/pull/45#issuecomment-4364503613`.

The first smoke started before the recreated backend had reached healthy and
failed with connection refused. The health wait was rerun without further env
changes and the endpoint probes passed.

Backend recreate and flag state:

```text
leadpeek-backend-1: Up (healthy)
ownership_flag_true: True
```

Endpoint smoke from inside the production backend container:

```text
0437312028: structure_parent=True ubo_depth_max=2 grandparent_seen=True parent_companies=1 ubo_edges=2
0476943753: structure_parent=True ubo_depth_max=3 grandparent_seen=True parent_companies=1 ubo_edges=4
0443891695: structure_parent=True ubo_depth_max=2 grandparent_seen=True parent_companies=1 ubo_edges=2
0431404530: structure_parent=True ubo_depth_max=2 grandparent_seen=True parent_companies=1 ubo_edges=2
backend health: {"status":"ok","service":"datasnoop-api"}
```

The `/structure` response now uses the graph-backed immediate-parent read path
for each sample, and `/ownership-graph?max_depth=6` returns the expected
multi-hop UBO chain.
