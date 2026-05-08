import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Pretendard',
          '-apple-system',
          '"Apple SD Gothic Neo"',
          '"Segoe UI"',
          'system-ui',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        ink: {
          50: '#f7f7f8',
          100: '#eeeef0',
          200: '#d8d9dd',
          300: '#b3b5bb',
          400: '#83868f',
          500: '#5d606a',
          600: '#43464f',
          700: '#33363d',
          800: '#23252b',
          900: '#16181c',
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
