// Vitest configuration for the frontend component tests.
// Mirrors the backend's pytest setup: `npm test` is a real gate (CI runs it via
// `npm test --if-present`), so a broken component fails the merge — not just the build.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
