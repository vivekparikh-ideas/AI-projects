import type { MetadataRoute } from "next";

// Installable PWA (D-036): Chrome on Android offers "Install app" from this manifest.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Nexus Investment Engine",
    short_name: "Nexus",
    description: "Your private AI investment team.",
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#070B10",
    theme_color: "#070B10",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
