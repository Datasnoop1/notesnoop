import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "NoteSnoop",
    short_name: "NoteSnoop",
    start_url: "/quick-capture",
    display: "standalone",
    background_color: "#f7f3ea",
    theme_color: "#10201c",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
    ],
  };
}
