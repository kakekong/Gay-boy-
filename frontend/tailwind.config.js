/** @type {import('tailwindcss').Config} */
//
// VOLER industrial design system.
//
// The whole app is re-skinned from here rather than screen by screen: every
// page already speaks in `brand-*` / `ink-*` utilities, so remapping those two
// scales restyles ~40 screens at once and keeps them in step forever after.
//
// One deliberate departure from the brand guide. It calls Industrial Orange
// the single accent, "used sparingly — one accent moment per view". In a dense
// operations app the primary buttons, active nav and links are *everywhere*;
// painting them all orange would be the opposite of sparing. So Voler Blue —
// the shield colour, already a brand colour — does the structural interactive
// work, and orange is held back for genuine emphasis: the focus ring, a page's
// main call to action, live figures, active underlines.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Body stays Inter — it is what the brand specifies and what the app
        // already reads well in at data density.
        sans: [
          "Inter var", "Inter", "ui-sans-serif", "system-ui",
          "-apple-system", "Segoe UI", "Roboto", "sans-serif",
        ],
        heading: ["Montserrat", "Helvetica Neue", "Arial", "sans-serif"],
        display: ["Bebas Neue", "Arial Narrow", "sans-serif"],
        mono: ["Roboto Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Voler Blue — the shield mark. Structural interactive colour.
        brand: {
          50:  "#eaf0f7",
          100: "#cbdbec",
          200: "#a9c1dd",
          300: "#6e97c2",
          400: "#4577ad",
          500: "#2a5992",
          600: "#214a7c",
          700: "#183a63",
          800: "#132e4f",
          900: "#0e2239",
        },
        // Industrial Orange — the accent. Used sparingly, on purpose.
        accent: {
          50:  "#fdf0e8",
          100: "#fbdcc9",
          300: "#f8a671",
          400: "#f5894a",
          500: "#f36c21",
          600: "#da5817",
          700: "#b5440d",
        },
        // Safety Yellow — rare, for hazard/spec emphasis only.
        safety: {
          300: "#ffd64d",
          400: "#ffc400",
          500: "#e6ac00",
        },
        // The steel scale. Black / engineering gray / steel gray / white do
        // the structural work; this replaces the old cool-graphite neutrals.
        ink: {
          50:  "#fafafa",
          100: "#f4f4f3",
          200: "#e8e8e6",
          300: "#d6d6d2",
          400: "#8c8c88",
          500: "#6e6e6e",
          600: "#555555",
          700: "#444444",
          800: "#2a2a2a",
          900: "#111111",
        },
      },
      // Machined edges. The brand allows 0–3px; `full` is kept because the
      // guide reserves pills for small tags and badges, which the app uses.
      borderRadius: {
        none: "0",
        sm: "1px",
        DEFAULT: "2px",
        md: "2px",
        lg: "3px",
        xl: "3px",
        "2xl": "3px",
        "3xl": "3px",
        full: "9999px",
      },
      // Hairline borders carry structure; shadows are for genuine overlays.
      boxShadow: {
        soft: "none",
        card: "0 1px 2px rgba(17,17,17,0.06)",
        hero: "0 12px 40px -16px rgba(17,17,17,0.28)",
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
      transitionTimingFunction: {
        // Mechanical, not springy.
        industrial: "cubic-bezier(0.2, 0, 0, 1)",
      },
    },
  },
  plugins: [],
};
