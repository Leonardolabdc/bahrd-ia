/** Ícones inline — sem biblioteca externa: são cinco, e o CSP do deploy é estrito. */

export const IconeMarca = () => (
  <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
    <rect x="0.5" y="0.5" width="25" height="25" rx="6" fill="var(--accent)" />
    <path
      d="M13 6.4c-2.7 0-4.9 2.1-4.9 4.7 0 3.4 4.9 8.5 4.9 8.5s4.9-5.1 4.9-8.5c0-2.6-2.2-4.7-4.9-4.7Z"
      fill="none"
      stroke="var(--accent-ink)"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
    <circle cx="13" cy="11" r="1.8" fill="var(--accent-ink)" />
  </svg>
);

export const Seta = () => (
  <svg className="seta" width="15" height="15" viewBox="0 0 15 15" aria-hidden="true">
    <path
      d="M5.5 3 10 7.5 5.5 12"
      stroke="currentColor"
      strokeWidth="1.6"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const SetaVoltar = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
    <path
      d="M8.5 2.5 4 7l4.5 4.5"
      stroke="currentColor"
      strokeWidth="1.6"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Chevron = () => (
  <svg className="chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
    <path
      d="M4.5 2.5 8 6l-3.5 3.5"
      stroke="currentColor"
      strokeWidth="1.5"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const Info = () => (
  <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
    <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.3" />
    <path d="M7 6.2v4M7 4.1v.9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const Confere = () => (
  <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
    <path
      d="M2.5 7.4l3 3 6-6.4"
      stroke="currentColor"
      strokeWidth="1.9"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/** Modo dia: aparece no modo noite, porque é para onde o clique leva. */
export const Sol = () => (
  <svg width="17" height="17" viewBox="0 0 18 18" aria-hidden="true">
    <circle cx="9" cy="9" r="3.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    <path
      d="M9 1.6v1.8M9 14.6v1.8M1.6 9h1.8M14.6 9h1.8M3.8 3.8l1.3 1.3M12.9 12.9l1.3 1.3M3.8 14.2l1.3-1.3M12.9 5.1l1.3-1.3"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  </svg>
);

/** Modo noite: aparece no modo dia. */
export const Lua = () => (
  <svg width="17" height="17" viewBox="0 0 18 18" aria-hidden="true">
    <path
      d="M15.2 11.1A6.6 6.6 0 0 1 6.9 2.8a6.6 6.6 0 1 0 8.3 8.3Z"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  </svg>
);

/** Lupa do campo de busca das listas de cartões: filtra pelo que já carregou. */
export const Lupa = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="6.8" cy="6.8" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
    <path d="M10.6 10.6l3.6 3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

/** A Visão geral: é painel de números, não fila de casos. */
export const Grafico = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
    <path
      d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
    />
  </svg>
);
