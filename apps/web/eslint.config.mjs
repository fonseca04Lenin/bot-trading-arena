import next from "eslint-config-next";

const config = [...next, { ignores: [".next/**", "src/lib/api-types.ts", "playwright-report/**"] }];
export default config;
