import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// The built app is served by the FastAPI backend (same origin) from `web/dist`, which the
// Modal image bakes in. During `npm run dev`, calls to /api and /font.ttf are proxied to a
// locally running `storeel serve` (default http://127.0.0.1:8000). The backend refuses
// cross-site writes by comparing Origin to Host, so the proxy strips the browser's Origin
// header (and does NOT rewrite Host) — that way uploads and other writes pass the guard in
// local dev. Set STOREEL_API to point elsewhere.
const API = process.env.STOREEL_API || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API,
        changeOrigin: false,
        configure: (proxy) => {
          // Drop Origin so the backend's same-site check sees no cross-site request.
          proxy.on("proxyReq", (proxyReq) => proxyReq.removeHeader("origin"));
        },
      },
      "/font.ttf": { target: API, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    // Vite emits hashed bundles under /assets, which the backend mounts.
    assetsDir: "assets",
  },
});
