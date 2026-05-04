/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          500: "#1f6feb",
          700: "#0a4cb1",
        },
      },
    },
  },
  plugins: [],
};
