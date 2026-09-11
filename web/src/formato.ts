/** Formatação compartilhada. Números em tabular-nums não podem "pular" na tela. */

export const mmss = (segundos: number): string =>
  `${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, "0")}`;

export const numeroBR = (n: number): string => n.toLocaleString("pt-BR");
