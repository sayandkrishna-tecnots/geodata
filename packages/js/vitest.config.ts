import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    // The cities table is 41 MB of JSON; parsing it once per worker dominates
    // the first test that touches it.
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
