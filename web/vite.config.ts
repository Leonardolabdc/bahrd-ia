import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // O mesmo atalho declarado em tsconfig.app.json. Sem isto, o TypeScript
  // aceitaria `@/algo` e o build quebraria — o editor concordando com um
  // import que o empacotador não resolve é pior que não ter atalho nenhum.
  resolve: {
    alias: { "@": "/src" },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Dentro do container o watcher nativo não enxerga alterações vindas do
    // bind mount do Windows/macOS — polling é o que faz o HMR funcionar.
    watch: { usePolling: true },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
