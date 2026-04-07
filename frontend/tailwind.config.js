/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0c10",
        surface: "rgba(255, 255, 255, 0.05)",
        primary: {
          light: "#00d2ff",
          DEFAULT: "#00b4d8",
          dark: "#0077b6",
        },
        accent: {
          cyan: "#00f5ff",
          blue: "#2d98ff",
          green: "#00ff9f",
        },
        border: "rgba(255, 255, 255, 0.1)",
      },
      backdropBlur: {
        xs: '2px',
      },
      animation: {
        'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(0, 245, 255, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(0, 245, 255, 0.6)' },
        }
      }
    },
  },
  plugins: [],
}
