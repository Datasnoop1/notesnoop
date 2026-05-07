import { clerkMiddleware } from '@clerk/nextjs/server'

/**
 * Phase 2 Clerk migration — gated proxy.
 *
 * Next.js 16 renamed the `middleware` file convention to `proxy`. This file
 * runs Clerk's request-side helpers (session refresh, auth context, etc.)
 * ONLY when the `NEXT_PUBLIC_USE_CLERK` flag is set to `"true"` at build
 * time. Otherwise we export a no-op function so the Supabase auth path
 * runs exactly as it did before this PR.
 *
 * The flag flip happens in Phase 5 (staging cutover) and Phase 6 (prod
 * cutover) per docs/auth-migration-clerk-final.md.
 */
export default process.env.NEXT_PUBLIC_USE_CLERK === 'true'
  ? clerkMiddleware()
  : () => {}

export const config = {
  matcher: [
    // Skip Next.js internals and all static files unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
}
