/** @type {import("next").NextConfig} */
const nextConfig = {
  // ESM packages used by react-markdown / remark
  transpilePackages: ["react-markdown", "remark-gfm"],

  async rewrites() {
    // Proxy /api/agent/* to the backend during local dev without Next.js API routes.
    // The dedicated route handlers in src/app/api/ take precedence over rewrites.
    return [];
  },
};

export default nextConfig;

