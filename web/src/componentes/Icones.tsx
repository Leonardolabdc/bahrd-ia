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
