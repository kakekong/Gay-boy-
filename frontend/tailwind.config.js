/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter var", "Inter", "ui-sans-serif", "system-ui",
          "-apple-system", "Segoe UI", "Roboto", "sans-serif",
        ],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        brand: {
          50:  "#eef4ff",
          100: "#dbe6ff",
          200: "#b7ccff",
          300: "#8aa9ff",
          400: "#5c80ff",
          500: "#3a5cf5",
          600: "#2a45d9",
          700: "#2236ad",
          800: "#1d2d8a",
          900: "#1a276f",
        },
        ink: {
          50:  "#f7f8fa",
          100: "#eef0f4",
          200: "#dde1e9",
          300: "#bcc3d1",
          400: "#8b94a7",
          500: "#5d6679",
          600: "#414b5e",
          700: "#2c3447",
          800: "#1c2233",
          900: "#0f1422",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(15,20,34,0.04), 0 1px 3px rgba(15,20,34,0.06)",
        card: "0 1px 3px rgba(15,20,34,0.06), 0 8px 24px -8px rgba(15,20,34,0.10)",
        hero: "0 30px 80px -30px rgba(58,92,245,0.45)",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      keyframes: {
        pulseSoft: {
          "0%,100%": { opacity: "1" },
          "50%":     { opacity: "0.55" },
        },
      },
      animation: {
        "pulse-soft": "pulseSoft 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
