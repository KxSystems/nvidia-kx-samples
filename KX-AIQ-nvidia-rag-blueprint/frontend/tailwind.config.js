/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        nvidia: {
          green: '#76B900',
          dark: '#1A1A1A',
          gray: {
            50: '#F5F5F5',
            100: '#E5E5E5',
            200: '#D4D4D4',
            300: '#A3A3A3',
            400: '#737373',
            500: '#525252',
            600: '#404040',
            700: '#262626',
            800: '#171717',
            900: '#0A0A0A',
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
