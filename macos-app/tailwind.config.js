/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/renderer/**/*.{js,jsx,ts,tsx,html}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface:  'var(--color-surface)',
        panel:    'var(--color-panel)',
        elevated: 'var(--color-elevated)',
        border:   'var(--color-border)',
        'border-subtle': 'var(--color-border-subtle)',
        text:     'var(--color-text)',
        muted:    'var(--color-muted)',
        subtle:   'var(--color-subtle)',
        amber:    'var(--color-amber)',
        'amber-dim': 'var(--color-amber-dim)',
        'amber-light': '#fbbf24',
        green:    'var(--color-green)',
        red:      'var(--color-red)',
        blue:     'var(--color-blue)',
        purple:   'var(--color-purple)',
        cyan:     'var(--color-cyan)',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Menlo', 'monospace'],
        ui:   ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'sans-serif'],
      },
      boxShadow: {
        'glow-amber': '0 0 16px -2px rgba(245, 158, 11, 0.25)',
        'glow-emerald': '0 0 16px -2px rgba(16, 185, 129, 0.25)',
        'glow-rose': '0 0 16px -2px rgba(244, 63, 94, 0.25)',
        'glow-cyan': '0 0 16px -2px rgba(6, 182, 212, 0.25)',
      },
      keyframes: {
        'fade-slide': {
          '0%':   { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-slide': 'fade-slide 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}

