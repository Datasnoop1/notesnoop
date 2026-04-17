import { permanentRedirect } from "next/navigation";

/* The page used to live here; renamed to /fallen-heroes after the
   operator wanted the URL to match the rebrand. We keep this route so
   any existing bookmarks / inbound links continue to work. Use
   `permanentRedirect` (HTTP 308) so search engines transfer link
   equity to the new URL. */
export default function GraveyardRedirect() {
  permanentRedirect("/fallen-heroes");
}
