import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, ErroDaApi } from "../api";
import { config } from "../config";
import type { SessaoDoPainel } from "../tipos";
import { ArteDaEntrada } from "./ArteDaEntrada";
import { Lua, Olho, OlhoRiscado, Sol } from "./Icones";
import { LogoQueAcende } from "./LogoQueAcende";
import { RotaDaEntrada, useCicloDaEntrada } from "./RotaDaEntrada";

/**
 * A tela de entrada da Central IA.
 *
 * Duas colunas. À esquerda, ocupando o resto da largura, um mapa de
 * rastreamento em vetor (`ArteDaEntrada`), por onde anda uma rota no vermelho
 * da marca (`RotaDaEntrada`) que termina na borda do mapa, na altura da marca
 * do Bahrd. À direita, numa coluna de fundo liso, a marca grande que acende
 * quando o sinal chega (`LogoQueAcende`) e o formulário. Um sinal sai de um
 * veículo, atravessa a cidade e chega à Central: é o que o sistema faz o dia
 * inteiro.
 *
 * A arte é enfeite e nada mais: `aria-hidden`, sem foco, sem clique. Até
 * 900 px o mapa vira uma faixa no topo e a rota some. Para quem pediu menos
 * movimento ao sistema, a tela fica parada. Os tokens de cor e o botão de sol
 * e lua são os do painel, e o mapa continua escuro nos dois temas, de
 * propósito (ver «ENTRADA» em `painel.css`).
 *
 * **O que ela não tem, de propósito:** "esqueci a senha" e cadastro. Os
 * usuários vêm da configuração do servidor (`PAINEL_USUARIOS`); quem perdeu a
 * senha pede uma nova a quem administra o sistema. Um botão que não leva a
 * lugar nenhum seria pior que botão nenhum. Primeiro acesso também não: sem
 * usuário configurado, o servidor nem liga o login.
 *
 * Os atalhos de teclado do painel (1 a 6, N, Esc) não existem aqui: o painel
 * nem está montado enquanto esta tela aparece, então digitar "n" no usuário
 * não troca o tema.
 */

const NOME_DO_AMBIENTE: Record<string, string> = {
  dev: "Ambiente de desenvolvimento",
  hml: "Ambiente de homologação",
};

function mensagemDe(erro: unknown): string {
  if (erro instanceof ErroDaApi) return erro.message;
  // `fetch` só rejeita sem resposta nenhuma: rede, DNS, CORS, API parada.
  return (
    `Não foi possível falar com a API em ${config.apiBaseUrl || "mesma origem"}. ` +
    `Confira a conexão e tente de novo.`
  );
}

export function Login({
  tema,
  aoAlternarTema,
  aoEntrar,
  aviso,
}: {
  tema: "claro" | "escuro";
  aoAlternarTema: () => void;
  aoEntrar: (sessao: SessaoDoPainel) => void;
  /** Por que a pessoa voltou para cá: sessão expirada, servidor sem login… */
  aviso?: string;
}) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(aviso ?? null);
  const [ambiente, setAmbiente] = useState<string | null>(null);
  const campoUsuario = useRef<HTMLInputElement>(null);
  const campoSenha = useRef<HTMLInputElement>(null);
  const raiz = useRef<HTMLDivElement>(null);
  const mapa = useRef<HTMLDivElement>(null);
  const marca = useRef<HTMLSpanElement>(null);
  const conteudo = useRef<HTMLDivElement>(null);

  useCicloDaEntrada(raiz);

  useEffect(() => {
    campoUsuario.current?.focus();
  }, []);

  // O ambiente vem da sonda de vida, que não pede login. O cabeçalho do painel
  // usa `/painel/estado`, e aqui ainda não há sessão para chamá-lo. Se a sonda
  // falhar, vale o que o `config.js` disse.
  useEffect(() => {
    let montado = true;
    api
      .vivo()
      .then((v) => montado && setAmbiente(v.ambiente))
      .catch(() => montado && setAmbiente(config.ambiente));
    return () => {
      montado = false;
    };
  }, []);

  const conferirCapsLock = (ev: KeyboardEvent<HTMLInputElement>) => {
    setCapsLock(ev.getModifierState("CapsLock"));
  };

  // Durante o envio os campos ficam `readOnly`, e não `disabled`: campo
  // desabilitado perde o foco, e depois de uma senha errada o foco precisa
  // voltar para a senha, não para o começo da página.
  async function enviar(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    if (enviando) return;

    if (!usuario.trim() || !senha) {
      setErro("Preencha o usuário e a senha.");
      (usuario.trim() ? campoSenha : campoUsuario).current?.focus();
      return;
    }

    setEnviando(true);
    setErro(null);
    try {
      await api.entrar(usuario.trim(), senha);
      aoEntrar(await api.sessaoAtual());
    } catch (e) {
      // 409: o servidor não tem login ligado (desenvolvimento sem usuários).
      // Não há o que errar aqui; o painel abre como abria antes do login.
      if (e instanceof ErroDaApi && e.status === 409) {
        try {
          aoEntrar(await api.sessaoAtual());
          return;
        } catch {
          // Segue para mostrar o motivo original.
        }
      }
      setErro(mensagemDe(e));
      setSenha("");
      campoSenha.current?.focus();
    } finally {
      setEnviando(false);
    }
  }

  const foraDeProducao = ambiente !== null && ambiente !== "prd-poc";

  return (
    <div className="entrada" ref={raiz}>
      <ArteDaEntrada ref={mapa} />
      <RotaDaEntrada raiz={raiz} mapa={mapa} marca={marca} conteudo={conteudo} />

      <main className="entrada-lado">
        <div className="entrada-topo">
          <button
            className="botao-icone"
            type="button"
            onClick={aoAlternarTema}
            aria-label={tema === "escuro" ? "Mudar para o modo dia" : "Mudar para o modo noite"}
            title={tema === "escuro" ? "Modo dia" : "Modo noite"}
          >
            {tema === "escuro" ? <Sol /> : <Lua />}
          </button>
        </div>

        <div className="entrada-conteudo" ref={conteudo}>
          {/* A mesma marca do cabeçalho, grande, onde a rota chega. Fora de
              produção, o selo do ambiente vem colado no nome: pequeno, mas
              antes do formulário, que é onde quem entra olha primeiro. */}
          <div className="entrada-marca">
            <LogoQueAcende ref={marca} />
            <span className="entrada-marca-logo">Bahrd</span>
            <span className="marca-risco entrada-marca-risco" aria-hidden="true" />
            <span className="entrada-marca-nome">Central IA</span>
            {foraDeProducao && (
              <span
                className="selo-ambiente entrada-selo"
                title={`${NOME_DO_AMBIENTE[ambiente] ?? `Ambiente ${ambiente}`}. Nada aqui é atendimento real.`}
              >
                <span aria-hidden="true">{ambiente.toUpperCase()}</span>
                <span className="entrada-so-leitor">
                  {NOME_DO_AMBIENTE[ambiente] ?? `Ambiente ${ambiente}`}
                </span>
              </span>
            )}
          </div>

          <form className="login-form" onSubmit={enviar} noValidate aria-labelledby="login-titulo">
            <h1 id="login-titulo" className="login-titulo">
              Entrar no painel
            </h1>

            <div className="campo login-campo">
              <label className="campo-nome" htmlFor="login-usuario">
                Usuário
              </label>
              <input
                ref={campoUsuario}
                id="login-usuario"
                name="username"
                type="text"
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder="seu usuário"
                value={usuario}
                onChange={(e) => setUsuario(e.target.value)}
                aria-invalid={erro !== null}
                aria-describedby={erro ? "login-erro" : undefined}
                readOnly={enviando}
              />
            </div>

            <div className="campo login-campo">
              <label className="campo-nome" htmlFor="login-senha">
                Senha
              </label>
              <div className="login-senha">
                <input
                  ref={campoSenha}
                  id="login-senha"
                  name="password"
                  type={mostrarSenha ? "text" : "password"}
                  autoComplete="current-password"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  value={senha}
                  onChange={(e) => setSenha(e.target.value)}
                  onKeyDown={conferirCapsLock}
                  onKeyUp={conferirCapsLock}
                  onBlur={() => setCapsLock(false)}
                  aria-invalid={erro !== null}
                  aria-describedby={
                    [erro ? "login-erro" : "", capsLock ? "login-caps" : ""].join(" ").trim() ||
                    undefined
                  }
                  readOnly={enviando}
                />
                <button
                  type="button"
                  className="login-olho"
                  onClick={() => {
                    setMostrarSenha((m) => !m);
                    campoSenha.current?.focus();
                  }}
                  aria-label={mostrarSenha ? "Ocultar a senha" : "Mostrar a senha"}
                  aria-pressed={mostrarSenha}
                  aria-controls="login-senha"
                  title={mostrarSenha ? "Ocultar a senha" : "Mostrar a senha"}
                >
                  {mostrarSenha ? <OlhoRiscado /> : <Olho />}
                </button>
              </div>
              {capsLock && (
                <span id="login-caps" className="login-caps">
                  Caps Lock ligado
                </span>
              )}
            </div>

            {/* `role="alert"` para o leitor de tela anunciar sem a pessoa ter de
                procurar. O texto é o `detail` da API, já em português. */}
            {erro && (
              <p id="login-erro" className="login-erro" role="alert">
                {erro}
              </p>
            )}

            <button
              type="submit"
              className="btn btn-primario login-entrar"
              disabled={enviando}
              aria-busy={enviando}
            >
              {enviando && <span className="login-giro" aria-hidden="true" />}
              {enviando ? "Entrando…" : "Entrar"}
            </button>
          </form>
        </div>

      </main>
    </div>
  );
}
