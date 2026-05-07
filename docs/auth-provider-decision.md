# Auth provider decision

Date: 2026-05-06

Decision: replace Supabase Auth with Clerk.

Context: Supabase free-tier pause broke login availability. DataSnoop needs one auth provider that is safe for a non-technical operator, durable on a free tier, and fast enough for a single 8 GB Hetzner box.

## Council result

Round 1 reached consensus, so Rounds 2 and 3 were not run.

| Juror | Round 1 vote | Risk note |
|---|---|---|
| kimi-k2.6 | OPTION_C Clerk | Misconfigured JWT template or claim mapping could lock users out. |
| qwen3.5:397b | OPTION_C Clerk | Vendor lock-in and cost jump beyond the free tier. |
| glm-5.1 | OPTION_C Clerk | Missing or wrong session-token claims could break auth silently. |
| gemma4:31b | OPTION_C Clerk | Single third-party SaaS dependency for identity. |
| devstral-2:123b | OPTION_C Clerk | Future pricing change, mitigated by grace period. |
| qwen3-coder-next | OPTION_C Clerk | Misreading retained-user overage metrics could trigger unexpected billing. |

Consensus pick: Clerk, 6/6 in Round 1.

Runner-up: Firebase Auth. It is operationally mature and has a broad free allowance, but the council preferred Clerk because comparable advanced controls are simpler to enable for this Next.js app and do not push the team toward Firebase Identity Platform tradeoffs.

## Deciding arguments

- SAFE: Clerk removes self-hosted auth uptime, SMTP, patching, nginx/fail2ban, and cutover complexity from the Hetzner box.
- SAFE: Clerk gives managed MFA, compromised-password checks, bot/attack protections, session controls, and strong Next.js integration.
- FREE: Clerk currently lists 50k monthly retained users and a one-month overage grace period, avoiding Supabase-style inactivity pause risk.
- PERFORMANCE: FastAPI can verify Clerk JWTs locally via cached JWKS, so normal API calls do not need a remote provider call.
- MIGRATION RISK: preserving the old Supabase UUID as `datasnoop_user_id` is the key safety requirement because favourites/projects use the auth user id.

## Implementation outline

Use `docs/auth-migration-clerk.md` as the working migration outline. The plan is a 6-phase managed-provider migration: configure Clerk, swap the Next.js SDK, replace FastAPI JWT verification, import users while preserving the old Supabase UUID in Clerk `external_id`, prove the full flow on staging, then cut production only after operator approval. The outline was reviewed once by the same six jurors; critical fixes were applied for production import, missing identity claims, password-reset handling, new-user UUID assignment, and rollback discipline.

## Operator decision

Recommended next step: approve Clerk as the auth provider and let Codex implement the migration outline phase by phase, staging first. Do not deploy anything until staging is proven and the operator explicitly approves production.
