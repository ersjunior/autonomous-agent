/** @type {import('next').NextConfig} */
const { version } = require("./package.json");

const nextConfig = {
  output: "standalone",
  devIndicators: {
    position: "bottom-right",
  },
  env: {
    NEXT_PUBLIC_APP_VERSION: version,
  },
};

module.exports = nextConfig;
