import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    proxy: {
      "/backend": {
        target: "http://127.0.0.1:8230",
        changeOrigin: false,
        ws: true,
        rewrite: (path) => path.replace(/^\/backend/, ""),
      },
    },
  },
});
