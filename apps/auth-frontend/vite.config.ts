import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser only ever sees one origin, so there is no CORS configuration and
// no cross-site cookie semantics to reason about — two of the easiest things to
// get subtly wrong in a login flow, removed rather than solved (P§3).
//
// The rewrite matters: the auth-server serves `/interaction`, not
// `/api/interaction`. Keeping the API at the root is what lets `/authorize`
// land there unprefixed at B2. This whole block disappears when Caddy arrives.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
