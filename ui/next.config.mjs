/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy API calls to the backend during development so the browser
  // never needs to know the backend port.  In production the frontend
  // and backend are served from the same origin.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8001/:path*",
      },
    ];
  },
};

export default nextConfig;
