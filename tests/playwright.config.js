// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1, // run tests sequentially to avoid local port collision
  retries: 0,
  reporter: [['list']],
  use: {
    actionTimeout: 0,
  },
});
