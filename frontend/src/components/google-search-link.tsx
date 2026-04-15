"use client";

import { ExternalLink, MapPin, Search } from "lucide-react";

/**
 * Wraps text with hover icons to search Google or Google Maps.
 * Shows small icons on hover — doesn't change the text appearance.
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

  return (
    <span className={`group/gs inline-flex items-center gap-1 ${className}`}>
      {children}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={type === "maps" ? `Search "${query}" on Google Maps` : `Search "${query}" on Google`}
        className="opacity-0 group-hover/gs:opacity-100 transition-opacity text-slate-400 hover:text-indigo-500"
        onClick={(e) => e.stopPropagation()}
      >
        <Icon className="h-3 w-3" />
      </a>
    </span>
  );
}

/**
 * Shows both Google Search and Maps icons on hover.
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
    <span className={`group/gs inline-flex items-center gap-1 ${className}`}>
      {children}
      <span className="opacity-0 group-hover/gs:opacity-100 transition-opacity inline-flex gap-0.5">
        <a
          href={`https://www.google.com/search?q=${encodeURIComponent(text)}`}
          target="_blank"
          rel="noopener noreferrer"
          title={`Search Google`}
          className="text-slate-400 hover:text-indigo-500"
          onClick={(e) => e.stopPropagation()}
        >
          <Search className="h-3 w-3" />
        </a>
        {mapsQuery && (
          <a
            href={`https://www.google.com/maps/search/${encodeURIComponent(mapsQuery)}`}
            target="_blank"
            rel="noopener noreferrer"
            title={`View on Google Maps`}
            className="text-slate-400 hover:text-indigo-500"
            onClick={(e) => e.stopPropagation()}
          >
            <MapPin className="h-3 w-3" />
          </a>
        )}
      </span>
    </span>
  );
}
