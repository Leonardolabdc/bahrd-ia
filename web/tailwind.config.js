/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // O preflight do Tailwind zera body, h1 e button — exatamente o que o sistema
  // de design do painel define em estilos/painel.css. Ligá-lo faria as duas
  // camadas brigarem na cascata, e a que perde é a validada com o time.
  // Os utilitários continuam disponíveis para componentes novos (D6).
  corePlugins: { preflight: false },
  theme: {
    extend: {
      // Os tokens do painel expostos ao Tailwind, para que um componente novo
      // use a mesma paleta sem duplicar valores.
      colors: {
        ground: "var(--ground)",
        surface: "var(--surface)",
        hairline: "var(--hairline)",
        ink: { DEFAULT: "var(--ink)", 2: "var(--ink-2)", 3: "var(--ink-3)" },
        accent: { DEFAULT: "var(--accent)", ink: "var(--accent-ink)", wash: "var(--accent-wash)" },
        critica: "var(--critica)",
        alta: "var(--alta)",
        media: "var(--media)",
        baixa: "var(--baixa)",
      },
      fontFamily: { ui: "var(--ui)", mono: "var(--mono)" },
    },
  },
  plugins: [],
};
