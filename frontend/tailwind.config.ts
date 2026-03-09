import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#11212d",
        slate: "#253745",
        mist: "#4a5c6a",
        fog: "#9ba8ab",
        milk: "#ccd0cf"
      }
    }
  },
  plugins: []
};

export default config;
