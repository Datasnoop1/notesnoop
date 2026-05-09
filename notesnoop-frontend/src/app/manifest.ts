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
