import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Chevron, Sair } from "./Icones";

/**
 * O nome de quem está no painel, no canto do cabeçalho, como botão de um menu
 * pequeno: quem é, com que perfil, e «Sair».
 *
 * Não tem «trocar a senha»: os usuários vêm da configuração do servidor
 * (`PAINEL_USUARIOS`), e trocar a senha é gerar a entrada de novo. Um item que
 * não pode funcionar não entra no menu.
 *
 * Teclado: Enter, Espaço ou seta para baixo abrem e põem o foco no «Sair»; Esc
 * fecha e devolve o foco ao nome; Tab para fora fecha. Clicar fora também
 * fecha. O Esc é pego antes do atalho do painel (que volta para a fila), para
 * fechar o menu não tirar ninguém da ocorrência que estava aberta.
 */
export function MenuDoUsuario({
  usuario,
  perfil,
  aoSair,
}: {
  usuario: string;
  perfil: "admin" | "operador";
  aoSair: () => void;
}) {
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const sair = useRef<HTMLButtonElement>(null);
  const idDoMenu = useId();
  const rotulo = perfil === "admin" ? "Admin" : "Operador";

  useEffect(() => {
    if (!aberto) return;
    sair.current?.focus();

    const clicouFora = (ev: PointerEvent) => {
      if (caixa.current && !caixa.current.contains(ev.target as Node)) setAberto(false);
    };
    // Na fase de captura, na `window`: roda antes do atalho de teclado do
    // painel, e o `stopPropagation` impede que o mesmo Esc ainda feche a
    // ocorrência aberta por baixo.
    const teclou = (ev: globalThis.KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      setAberto(false);
      botao.current?.focus();
    };
    document.addEventListener("pointerdown", clicouFora);
    window.addEventListener("keydown", teclou, true);
    return () => {
      document.removeEventListener("pointerdown", clicouFora);
      window.removeEventListener("keydown", teclou, true);
    };
  }, [aberto]);

  const noBotao = (ev: KeyboardEvent<HTMLButtonElement>) => {
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setAberto(true);
    }
  };

  // Um item só: as setas mantêm o foco nele em vez de deixá-lo escapar.
  const noMenu = (ev: KeyboardEvent<HTMLDivElement>) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp" || ev.key === "Home" || ev.key === "End") {
      ev.preventDefault();
      sair.current?.focus();
    }
  };

  return (
    <div
      className="menu-usuario"
      ref={caixa}
      // Tab para fora fecha. Só com destino conhecido: o Safari não dá foco ao
      // botão clicado, e sem esta condição clicar no nome com o menu aberto o
      // fecharia aqui e o reabriria no clique. O clique fora é do `pointerdown`.
      onBlur={(ev) => {
        const destino = ev.relatedTarget as Node | null;
        if (aberto && destino && !ev.currentTarget.contains(destino)) setAberto(false);
      }}
    >
      <button
        ref={botao}
        type="button"
        className="menu-usuario-botao"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idDoMenu : undefined}
        onClick={() => setAberto((a) => !a)}
        onKeyDown={noBotao}
        title={`Conectado como ${usuario}`}
      >
        <span className="usuario-nome">{usuario}</span>
        <span className={`selo-perfil selo-perfil-${perfil}`}>{rotulo}</span>
        <Chevron />
      </button>

      {aberto && (
        <div
          id={idDoMenu}
          className="menu-usuario-lista"
          role="menu"
          aria-label={`Conta de ${usuario}`}
          onKeyDown={noMenu}
        >
          {/* Informação, não ação: fica fora da ordem do menu. */}
          <div className="menu-usuario-quem" role="presentation">
            <span className="menu-usuario-rotulo">Conectado como</span>
            <b className="menu-usuario-nome">{usuario}</b>
            <span className="menu-usuario-perfil">
              Perfil <span className={`selo-perfil selo-perfil-${perfil}`}>{rotulo}</span>
            </span>
          </div>
          <button
            ref={sair}
            type="button"
            role="menuitem"
            className="menu-usuario-item"
            onClick={() => {
              setAberto(false);
              aoSair();
            }}
          >
            <Sair />
            Sair
          </button>
        </div>
      )}
    </div>
  );
}
