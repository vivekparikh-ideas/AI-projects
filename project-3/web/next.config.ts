import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Local dev only: let a phone on the same Wi-Fi load dev assets (e.g. NEXUS_DEV_ORIGINS=192.168.86.45).
  allowedDevOrigins: (process.env.NEXUS_DEV_ORIGINS ?? "").split(",").filter(Boolean),
  // Local dev only: proxy /api to the FastAPI server. On Vercel, Services route /api to the backend.
  rewrites() {
    const api = process.env.NEXUS_API_URL;
    return api ? [{ source: "/api/:path*", destination: `${api}/api/:path*` }] : [];
  },
};

export default nextConfig;
