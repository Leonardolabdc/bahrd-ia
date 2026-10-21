import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, ErroDaApi } from "../api";
import { config } from "../config";
import type { SessaoDoPainel } from "../tipos";
import { Lua, Olho, OlhoRiscado, Sol } from "./Icones";
import { Marca } from "./Marca";

/**
 * A tela de login da Central IA.
 *
 * É a primeira coisa que alguém vê do produto, então ela é o mesmo produto: a
 * marca do cabeçalho, a linha vermelha com o brilho, os mesmos tokens de cor e
 * o mesmo botão de sol e lua. Nada de identidade própria de "tela de login".
 *
 * **O que ela não tem, de propósito:** "esqueci a senha" e cadastro. Os
 * usuários vêm da configuração do servidor (`PAINEL_USUARIOS`); quem perdeu a
 * senha pede uma nova a quem administra o sistema. Um link que não leva a
 * lugar nenhum seria pior que link nenhum.
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
    <div className="login">
      <header className="topo">
        <div className="faixa">
          <div className="marca">
            <Marca />
            <span className="marca-logo">Bahrd</span>
            <span className="marca-risco" aria-hidden="true" />
            <span className="marca-nome">Central IA</span>
          </div>
          <div className="topo-dir">
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
        </div>
      </header>

      {/* A mesma linha vermelha do painel, com o mesmo brilho, vinda da mesma
          regra de CSS. Aqui ela separa a marca do formulário, como lá separa
          a marca das abas. */}
      <div className="segmentos login-linha" aria-hidden="true" />

      <main className="login-corpo">
        <form className="login-cartao" onSubmit={enviar} noValidate aria-labelledby="login-titulo">
          <div className="login-cab">
            <h1 id="login-titulo" className="login-titulo">
              Entrar no painel
            </h1>
            <p className="login-sub">
              Use o usuário e a senha que a administração do sistema passou para você.
            </p>
          </div>

          {foraDeProducao && (
            <p
              className="login-ambiente"
              title={`Ambiente de ${ambiente}. Nada aqui é atendimento real.`}
            >
              <span className="selo-ambiente">{ambiente.toUpperCase()}</span>
              {NOME_DO_AMBIENTE[ambiente] ?? `Ambiente ${ambiente}`}
            </p>
          )}

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
      </main>

      <footer className="pe">
        <div className="quadro largo">
          <span>Painel do operador · POC de IA da Central Bahrd</span>
        </div>
      </footer>
    </div>
  );
}
