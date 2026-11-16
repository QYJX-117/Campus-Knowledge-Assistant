/** Vite config for building the Campus QA Widget as a standalone library */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: "src/widget.tsx",
      name: "HHUChat",
      formats: ["umd"],
      fileName: () => "widget.js",
    },
    rollupOptions: {
      // External: React is NOT bundled (assumes host page provides it)
      // For zero-dependency embed, remove these and accept larger bundle
      external: [],
      output: {
        globals: {},
        inlineDynamicImports: true,
        exports: "named",
      },
    },
    outDir: "dist-widget",
    emptyOutDir: true,
    // Inline CSS in JS
    cssCodeSplit: false,
  },
  // Ensure CSS ?inline works
  css: {
    modules: false,
  },
});
