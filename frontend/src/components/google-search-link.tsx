"use client";

import { MapPin, Search } from "lucide-react";

/**
 * Wraps text with a visible search icon linking to Google or Google Maps.
 * Icon is always visible (muted) and highlights on hover.
 * Text gets a subtle underline on hover to signal clickability.
 */
export function GoogleSearchLink({
  query,
  type = "search",
  children,
  className = "",
}: {
  query: string;
  type?: "search" | "maps";
  children: React.ReactNode;
  className?: string;
}) {
  const url =
    type === "maps"
      ? `https://www.google.com/maps/search/${encodeURIComponent(query)}`
      : `https://www.google.com/search?q=${encodeURIComponent(query)}`;
  const Icon = type === "maps" ? MapPin : Search;
  const tooltip =
    type === "maps" ? `Search "${query}" on Google Maps` : `Search "${query}" on Google`;

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={tooltip}
      className={`group/gs inline-flex items-center gap-1 hover:underline decoration-slate-300 underline-offset-2 ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
      <Icon className="h-3.5 w-3.5 text-brand/60 group-hover/gs:text-brand transition-colors shrink-0" />
    </a>
  );
}

/**
 * Shows Google Search and Maps icons (always visible).
 * Text underlines on hover to signal clickability.
 */
export function SearchableText({
  text,
  mapsQuery,
  children,
  className = "",
}: {
  text: string;
  mapsQuery?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={`group/gs inline-flex items-center gap-1.5 ${className}`}>
      <span className="group-hover/gs:underline decoration-slate-300 underline-offset-2">{children}</span>
      <span className="inline-flex items-center gap-0.5 shrink-0">
        <a
          href={`https://www.google.com/search?q=${encodeURIComponent(text)}`}
          target="_blank"
          rel="noopener noreferrer"
          title="Search Google"
          className="text-brand/60 hover:text-brand transition-colors"
          onClick={(e) => e.stopPropagation()}
        >
          <Search className="h-3.5 w-3.5" />
        </a>
        {mapsQuery && (
          <a
            href={`https://www.google.com/maps/search/${encodeURIComponent(mapsQuery)}`}
            target="_blank"
            rel="noopener noreferrer"
            title="View on Google Maps"
            className="text-brand/60 hover:text-brand transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <MapPin className="h-3.5 w-3.5" />
          </a>
        )}
      </span>
    </span>
  );
}
