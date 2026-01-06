/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "../backend/templates/**/*.html",
    "../backend/ipam/templates/**/*.html",
    "./src/**/*.js",
  ],
  safelist: [
    // IP状态颜色 - 确保这些类始终被生成
    'bg-emerald-500', 'dark:bg-emerald-500', 'hover:bg-emerald-400', 'dark:hover:bg-emerald-400',
    'bg-purple-500', 'dark:bg-purple-500', 'hover:bg-purple-400', 'dark:hover:bg-purple-400',
    'bg-blue-500', 'dark:bg-blue-500', 'hover:bg-blue-400', 'dark:hover:bg-blue-400',
    'bg-amber-500', 'dark:bg-amber-500', 'hover:bg-amber-400', 'dark:hover:bg-amber-400',
    'bg-red-500', 'dark:bg-red-500', 'hover:bg-red-400', 'dark:hover:bg-red-400',
    'bg-slate-200', 'dark:bg-slate-700',
    'text-white', 'text-slate-500', 'dark:text-slate-400',
    'animate-pulse',
  ],
  theme: {
    extend: {
      colors: {
        // CALB主题色 - 蓝色系
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        // 次要色 - 灰色系
        secondary: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
        // 成功色 - 绿色
        success: {
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
        },
        // 警告色 - 橙色
        warning: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
          800: '#92400e',
          900: '#78350f',
        },
        // 危险色 - 红色
        danger: {
          50: '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#fca5a5',
          400: '#f87171',
          500: '#ef4444',
          600: '#dc2626',
          700: '#b91c1c',
          800: '#991b1b',
          900: '#7f1d1d',
        },
        // IP状态色
        ip: {
          available: '#22c55e',
          allocated: '#3b82f6',
          reserved: '#f59e0b',
          conflict: '#ef4444',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)',
        'card-hover': '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
        'modal': '0 25px 50px -12px rgb(0 0 0 / 0.25)',
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
