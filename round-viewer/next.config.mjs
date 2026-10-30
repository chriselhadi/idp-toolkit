/** @type {import('next').NextConfig} */
const nextConfig = {
  // Patient data: no page may be cached by a browser or a shared cache, and none may be framed.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cache-Control", value: "private, no-store" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
  serverExternalPackages: ["xlsx"],
};

export default nextConfig;
