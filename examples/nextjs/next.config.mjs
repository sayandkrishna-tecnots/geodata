/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keeps geodata-js out of every serverless function's file trace.
  //
  // Without this, Next tries to bundle the package into each route that
  // imports it, and any route touching `geodata-js/cities` drags 41 MB of city
  // data into its lambda. Marked external, the package is loaded from
  // node_modules at runtime instead -- the data is read once, by the one
  // process that needs it.
  serverExternalPackages: ["geodata-js"],

  // This example consumes the package through a `file:` dependency, which npm
  // installs as a symlink out of the project root. webpack resolves symlinks
  // to their real path by default, which lands outside the app and fails to
  // resolve. Turning that off keeps the module at its node_modules path.
  //
  // Only needed because the package lives in the same repo. A consumer
  // installing `geodata-js` from npm needs none of this.
  webpack: (config) => {
    config.resolve.symlinks = false;
    return config;
  },

  // File tracing has to start above the app for the same reason: the package's
  // real files are two directories up.
  outputFileTracingRoot: new URL("../..", import.meta.url).pathname,
};

export default nextConfig;
