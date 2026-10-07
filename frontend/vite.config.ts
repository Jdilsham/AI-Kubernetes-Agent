import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // `npm run dev`: forward /api to a locally running backend (same-origin, like nginx in production)
  server: {
    proxy: { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:9000" },
  },
});
