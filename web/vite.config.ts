import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    base: env.VITE_BASE || "/",
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5176,
      strictPort: true,
      proxy: {
        "/api": {
          target: process.env.VITE_API_URL || "http://127.0.0.1:8002",
          changeOrigin: true,
        },
        "/tpe-api": {
          target: process.env.VITE_TPE_API_URL || "http://127.0.0.1:8010",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/tpe-api/, ""),
        },
      },
    },
  };
});
