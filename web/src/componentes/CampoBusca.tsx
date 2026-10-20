import { Lupa } from "./Icones";

/**
 * Campo de busca por texto, acima de cada lista de cartões.
 *
 * Filtra em cima do que já chegou da API — sem round-trip ao servidor, sem
 * Enter nem botão. Compartilhado pelas quatro listas que mostram cartões
 * (atendimento humano, atendimento IA, desativados, números removidos e
 * encerrados) para não repetir o mesmo JSX e o mesmo estilo quatro vezes.
 */
export function CampoBusca({
  valor,
  aoMudar,
  placeholder,
}: {
  valor: string;
  aoMudar: (valor: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="campo-busca">
      <Lupa />
      <input
        type="text"
        value={valor}
        onChange={(e) => aoMudar(e.target.value)}
        placeholder={placeholder ?? "Buscar"}
        aria-label={placeholder ?? "Buscar"}
      />
    </label>
  );
}
