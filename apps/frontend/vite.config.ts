import { defineConfig } from "vite";
import solidPlugin from "vite-plugin-solid";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [solidPlugin(), tailwindcss()],
  server: {
    port: 4001,
    host: "0.0.0.0",
    proxy: {
      "/api": "http://localhost:4000",
      "/hubs": {
        target: "http://localhost:4000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "esnext",
    sourcemap: "hidden",
  },
});
