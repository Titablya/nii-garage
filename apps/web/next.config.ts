import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker uses standalone output; Windows local builds avoid its symlink step.
  output: process.platform === "win32" ? undefined : "standalone",
  poweredByHeader: false,
  async rewrites() {
    const internalApiUrl = process.env.INTERNAL_API_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${internalApiUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
