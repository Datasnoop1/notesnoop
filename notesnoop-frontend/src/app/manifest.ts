import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "NoteSnoop",
    short_name: "NoteSnoop",
    id: "/quick-capture",
    start_url: "/quick-capture",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f7f3ea",
    theme_color: "#10201c",
    categories: ["productivity", "business"],
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      {
        name: "Quick capture",
        short_name: "Capture",
        url: "/quick-capture",
      },
    ],
  };
}
