/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        medpark: {
          50: '#f0f5fa',
          100: '#e1ecf5',
          500: '#005596', // Medpark Blue
          600: '#004377',
          700: '#00335c',
          900: '#001e38',
        }
      }
    },
  },
  plugins: [],
}
