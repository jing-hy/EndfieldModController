/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,js}"],
  darkMode: "class",
  theme: {
    extend: {
      // 颜色全部走 CSS 变量（tokens.css），这样暗色主题只换变量、不动组件
      colors: {
        bg: "var(--bg)",
        surface: { DEFAULT: "var(--surface)", 2: "var(--surface-2)" },
        line: { DEFAULT: "var(--border)", strong: "var(--border-strong)" },
        ink: { DEFAULT: "var(--text)", muted: "var(--text-muted)" },
        accent: { DEFAULT: "var(--accent)", hover: "var(--accent-hover)", soft: "var(--accent-soft)" },
        danger: "var(--danger)",
        success: "var(--success)",
        warn: "var(--warn)",
      },
      // 排版比例：收敛到 6 档（旧界面混用 12/13/15）
      fontSize: {
        xs: ["12px", "18px"], sm: ["13px", "20px"], base: ["14px", "22px"],
        lg: ["16px", "24px"], xl: ["20px", "28px"], "2xl": ["24px", "32px"],
      },
      // 圆角收紧（旧界面 10/16 偏大）
      borderRadius: { sm: "6px", DEFAULT: "8px", md: "8px", lg: "10px", xl: "14px" },
      // 层次三档，取代旧的"高饱和主色 + 大圆角 + 重阴影"
      boxShadow: {
        sm: "var(--sh-sm)", DEFAULT: "var(--sh-sm)",
        md: "var(--sh-md)", lg: "var(--sh-lg)",
      },
      fontFamily: { sans: ["var(--font-sans)"] },
    },
  },
  plugins: [],
};
