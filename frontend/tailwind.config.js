/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        base: {
          950: "#0a0a0b",
          900: "#111113",
          850: "#16171a",
          800: "#1c1d21",
          700: "#26272c",
          600: "#35373d",
          500: "#4a4c54",
        },
        ink: {
          100: "#f3f1ee",
          300: "#c9c7c3",
          500: "#8b8a87",
        },
        accent: {
          900: "#3a0d0d",
          700: "#7a1d1d",
          600: "#9c2323",
          500: "#c22e2e",
          400: "#e6483f",
        },
        up: "#3fb37f",
        down: "#d1453d",
      },
      fontFamily: {
        sans: ["Archivo", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
