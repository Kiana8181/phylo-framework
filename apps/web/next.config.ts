import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  ...(process.env.TEST_BROWSER_COVERAGE === "1" ? {
    webpack: (config: any) => {
      config.module.rules.push({
        test: /\.[jt]sx?$/,
        include: [/apps[\\/]web[\\/](app|components|features|lib)[\\/]/],
        enforce: "post",
        use: [{loader: require.resolve("../../scripts/coverage-loader.cjs")}],
      });
      return config;
    },
  } : {})
};

export default nextConfig;
