import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: browser calls /solr and /iiif and /data on the Vite server,
// which forwards to the docker services. In production nginx does the same.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/solr": { target: "http://localhost:8983", changeOrigin: true },
      "/iiif": { target: "http://localhost:8182", changeOrigin: true },
      "/data": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
