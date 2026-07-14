/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
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
        // Refined indigo — deeper and less neon than the old royal blue.
        brand: {
          50:  "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        // Cool graphite neutrals — the canvas sits a step darker so the
        // UI reads calm instead of glaring white.
        ink: {
          50:  "#f6f7f9",
          100: "#eceef2",
          200: "#dbdfe7",
          300: "#b7bdc9",
          400: "#878f9f",
          500: "#5b6372",
          600: "#3f4654",
          700: "#2a303d",
          800: "#191e28",
          900: "#0d1117",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(13,17,23,0.05)",
        card: "0 2px 4px rgba(13,17,23,0.04), 0 12px 32px -12px rgba(13,17,23,0.14)",
        hero: "0 30px 80px -30px rgba(79,70,229,0.40)",
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
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
