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
    },
  };
});
