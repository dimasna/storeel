import { defineConfig, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// The built app is served by the FastAPI backend (same origin) from `web/dist`, which the
// Modal image bakes in. During `npm run dev`, calls to /api and /font.ttf are proxied to a
// locally running `storeel serve`. It takes port 8000, or the next free port when another app
// already has 8000, so the backend is looked up by name on ports 8000-8019 (set STOREEL_API to
// skip the search). The backend refuses cross-site writes by comparing Origin to Host, so the
// proxy strips the browser's Origin header (and does NOT rewrite Host) — that way uploads and
// other writes pass the guard in local dev.
async function findStudio(): Promise<string> {
  if (process.env.STOREEL_API) return process.env.STOREEL_API;
  for (let port = 8000; port < 8020; port++) {
    const url = `http://127.0.0.1:${port}`;
    try {
      const response = await fetch(`${url}/api/openapi.json`, { signal: AbortSignal.timeout(500) });
      const spec = (response.ok ? await response.json() : null) as { info?: { title?: string } } | null;
      if (spec?.info?.title === "Storeel Studio") return url;
    } catch {
      // nothing on this port, or not an HTTP server
    }
  }
  console.warn(
    "\n[storeel] No studio backend found on ports 8000-8019. Start `storeel serve`, then restart" +
      " `npm run dev` (or set STOREEL_API).\n",
  );
  return "http://127.0.0.1:8000";
}

export default defineConfig(async (): Promise<UserConfig> => {
  const API = await findStudio();
  console.log(`\n[storeel] /api calls go to ${API}\n`);
  return {
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
  };
});
