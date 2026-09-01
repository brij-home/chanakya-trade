/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/renderer/**/*.{js,jsx,ts,tsx,html}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        /* ── Backgrounds ── */
        void:     'var(--color-void)',
        surface:  'var(--color-surface)',
        panel:    'var(--color-panel)',
        elevated: 'var(--color-elevated)',
        highlight:'var(--color-highlight)',
        border:   'var(--color-border)',
        'border-subtle': 'var(--color-border-subtle)',

        /* ── Text ── */
        text:     'var(--color-text)',
        'text-dim': 'var(--color-text-dim)',
        muted:    'var(--color-muted)',
        subtle:   'var(--color-subtle)',

        /* ── Semantic accents ── */
        gold:        'var(--color-gold)',
        'gold-bright':'var(--color-gold-bright)',
        'gold-dim':  'var(--color-gold-dim)',

        emerald:        'var(--color-emerald)',
        'emerald-bright':'var(--color-emerald-bright)',
        'emerald-dim':  'var(--color-emerald-dim)',

        rose:        'var(--color-rose)',
        'rose-bright':'var(--color-rose-bright)',
        'rose-dim':  'var(--color-rose-dim)',

        sapphire:        'var(--color-sapphire)',
        'sapphire-bright':'var(--color-sapphire-bright)',
        'sapphire-dim':  'var(--color-sapphire-dim)',

        violet:        'var(--color-violet)',
        'violet-bright':'var(--color-violet-bright)',
        'violet-dim':  'var(--color-violet-dim)',

        cyan:        'var(--color-cyan)',
        'cyan-bright':'var(--color-cyan-bright)',
        'cyan-dim':  'var(--color-cyan-dim)',

        /* ── Backward-compatibility aliases ── */
        amber:       'var(--color-amber)',
        'amber-dim': 'var(--color-amber-dim)',
        'amber-light':'#ffbb40',
        green:       'var(--color-green)',
        red:         'var(--color-red)',
        blue:        'var(--color-blue)',
        purple:      'var(--color-purple)',
      },

      fontFamily: {
        ui:   ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Menlo', 'Consolas', 'monospace'],
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },

      fontSize: {
        '2xs': ['9px',  { lineHeight: '1.4' }],
        xs:    ['11px', { lineHeight: '1.5' }],
        sm:    ['12px', { lineHeight: '1.55' }],
        base:  ['13px', { lineHeight: '1.6' }],
        lg:    ['14px', { lineHeight: '1.6' }],
        xl:    ['16px', { lineHeight: '1.5' }],
        '2xl': ['20px', { lineHeight: '1.4' }],
        '3xl': ['24px', { lineHeight: '1.3' }],
        '4xl': ['28px', { lineHeight: '1.25' }],
      },

      borderRadius: {
        xs:  '4px',
        sm:  '6px',
        md:  '8px',
        lg:  '10px',
        xl:  '12px',
        '2xl':'14px',
        '3xl':'18px',
        '4xl':'22px',
      },

      boxShadow: {
        /* Depth shadows */
        'card':  '0 1px 3px rgba(0,0,0,0.5), 0 4px 16px rgba(0,0,0,0.35)',
        'float': '0 8px 32px rgba(0,0,0,0.65), 0 2px 8px rgba(0,0,0,0.4)',
        'modal': '0 24px 64px rgba(0,0,0,0.85), 0 8px 24px rgba(0,0,0,0.55)',

        /* Glow shadows */
        'glow-gold':    '0 0 20px -4px rgba(245, 166, 35, 0.50)',
        'glow-emerald': '0 0 20px -4px rgba(0, 214, 143, 0.50)',
        'glow-rose':    '0 0 20px -4px rgba(255, 79, 123, 0.50)',
        'glow-sapphire':'0 0 20px -4px rgba(77, 155, 255, 0.50)',
        'glow-cyan':    '0 0 20px -4px rgba(0, 223, 224, 0.50)',
        'glow-violet':  '0 0 20px -4px rgba(157, 125, 255, 0.50)',

        /* Legacy compat */
        'glow-amber':   '0 0 16px -2px rgba(245, 158, 11, 0.25)',
        xs: '0 0 0 1px rgba(0,0,0,0.05)',
        sm: '0 1px 2px 0 rgba(0,0,0,0.08)',
      },

      spacing: {
        '13': '3.25rem',
        '15': '3.75rem',
        '18': '4.5rem',
        '22': '5.5rem',
        '26': '6.5rem',
        '30': '7.5rem',
      },

      animation: {
        /* Core system animations */
        'fade-slide':       'fade-slide 0.30s cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-up-fade':    'slide-up-fade 0.28s cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-down-fade':  'slide-down-fade 0.22s cubic-bezier(0.16, 1, 0.3, 1) both',
        'stream-in':        'stream-in 0.18s cubic-bezier(0.16, 1, 0.3, 1) both',
        'toast-in':         'toast-in 0.32s cubic-bezier(0.34, 1.56, 0.64, 1) both',
        'toast-out':        'toast-out 0.25s cubic-bezier(0.4, 0, 1, 1) both',
        'gold-pulse':       'gold-pulse 2.0s ease-in-out infinite',
        'glow-pulse':       'glow-pulse 2.0s ease-in-out infinite',
        'cursor-blink':     'cursor-blink 1.1s step-end infinite',
        'price-flash-up':   'price-flash-up 0.65s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'price-flash-down': 'price-flash-down 0.65s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'skeleton-shimmer': 'skeleton-shimmer 1.6s ease-in-out infinite',
        'arc-draw':         'arc-draw 0.8s cubic-bezier(0.16, 1, 0.3, 1) both',
        'pipeline-fill':    'pipeline-fill 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'rotate-gradient':  'rotate-gradient 3s ease infinite',
        'number-flash':     'number-flash 0.4s ease-in-out',
      },

      keyframes: {
        'fade-slide': {
          '0%':   { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-up-fade': {
          '0%':   { opacity: '0', transform: 'translateY(10px) scale(0.98)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'slide-down-fade': {
          '0%':   { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'stream-in': {
          '0%':   { opacity: '0', transform: 'translateX(-4px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'toast-in': {
          '0%':   { opacity: '0', transform: 'translateX(100%)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'toast-out': {
          '0%':   { opacity: '1', transform: 'translateX(0)' },
          '100%': { opacity: '0', transform: 'translateX(110%)' },
        },
        'gold-pulse': {
          '0%, 100%': { boxShadow: '0 0 6px 0px rgba(245, 166, 35, 0.45)' },
          '50%':       { boxShadow: '0 0 18px 4px rgba(245, 166, 35, 0.75)' },
        },
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 6px 0px rgba(0, 214, 143, 0.5)' },
          '50%':       { boxShadow: '0 0 14px 3px rgba(0, 214, 143, 0.8)' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0' },
        },
        'price-flash-up': {
          '0%':   { backgroundColor: 'transparent' },
          '15%':  { backgroundColor: 'rgba(0, 214, 143, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        'price-flash-down': {
          '0%':   { backgroundColor: 'transparent' },
          '15%':  { backgroundColor: 'rgba(255, 79, 123, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        'skeleton-shimmer': {
          '0%':   { backgroundPosition: '-600px 0' },
          '100%': { backgroundPosition: '600px 0' },
        },
        'arc-draw': {
          '0%':   { strokeDashoffset: '200' },
          '100%': { strokeDashoffset: '0' },
        },
        'pipeline-fill': {
          '0%':   { width: '0%' },
          '100%': { width: '100%' },
        },
        'rotate-gradient': {
          '0%':   { backgroundPosition: '0% 50%' },
          '50%':  { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
        'number-flash': {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0.4' },
        },
      },

      transitionTimingFunction: {
        'ease-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
        'ease-out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
        'ease-in-expo':  'cubic-bezier(0.7, 0, 0.84, 0)',
      },

      backdropBlur: {
        xs: '2px',
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
        '2xl': '24px',
      },

      zIndex: {
        '60': '60',
        '70': '70',
        '80': '80',
        '90': '90',
        '100': '100',
        '9999': '9999',
      },
    },
  },
  plugins: [],
}
