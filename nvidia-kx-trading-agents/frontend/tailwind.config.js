/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // NVIDIA Trading Agents — light "white + blue" theme.
        // The token NAMES are kept (green/gray-*) for class-name compatibility, but the
        // VALUES are re-themed: `green` is now the blue accent, and the `gray` scale is
        // INVERTED vs the old dark theme — high numbers (900/800) are now the lightest
        // surfaces and low numbers (50/100) are the darkest ink. Because the codebase used
        // the scale monotonically (bg at 900/800, text at 300-500), this inversion flips
        // the whole UI to light without touching the class names.
        nvidia: {
          green: '#2563EB',   // accent (blue-600) — buttons, links, active, focus rings
          dark: '#0F172A',    // strong ink
          gray: {
            50:  '#0F172A',   // ink / primary text (replaces old text-white via swap)
            100: '#1E293B',   // strong text
            200: '#334155',   // text
            300: '#475569',   // secondary-strong text
            400: '#64748B',   // muted text (most common)
            500: '#94A3B8',   // faint text / placeholder / disabled
            600: '#CBD5E1',   // input + strong borders
            700: '#E2E8F0',   // borders / dividers / subtle fills / secondary buttons
            800: '#FFFFFF',   // cards / panels
            900: '#F1F5F9',   // page background
          }
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-in-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        }
      }
    },
  },
  plugins: [],
}
