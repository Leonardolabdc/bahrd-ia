/**
 * Espelho dos esquemas de `central_ia/api/esquemas_painel.py`.
 *
 * Mantidos à mão de propósito nesta fase: gerar o cliente a partir do OpenAPI
 * vale a pena quando a superfície da API para de mudar toda semana. Até lá, o
 * gerador esconderia mudanças de contrato que agora aparecem no `tsc`.
 */

export type Grau = "critica" | "alta" | "media" | "baixa";
export type Quem = "ia" | "cliente";

/** O canal decide COMO a conversa é exibida, não só por onde ela passou. */
export type Canal = "LIGACAO" | "AUDIO" | "TEXTO";

export const CANAL_ROTULO: Record<Canal, string> = {
  LIGACAO: "Ligação",
  AUDIO: "Áudio no WhatsApp",
  TEXTO: "WhatsApp",
};

export interface PassoRoteiro {
  frase: string;
  duracao_s: number;
  falando: boolean;
}

export interface Turno {
  quem: Quem;
  fala: string;
  horario: string | null;
  tipo: "texto" | "audio" | "botoes" | "template";
  duracao_s: number | null;
  botoes: string[];
  status: "enviado" | "entregue" | "lido" | null;
  /** O texto veio de STT, não foi digitado. Muda como o operador deve lê-lo. */
  transcrito: boolean;
}

export interface ItemFila {
  ocorrencia_id: string;
  grau: Grau;
  tipo_evento: string;
  canal: Canal;
  placa: string;
  interlocutor: string;
  nota: string | null;
  /**
   * `link` (evento real) ou `teste` (disparado pela tela da Central).
   *
   * ⛔ Vira selo na linha da fila. Sem ele, um pânico disparado para
   * experimentar tem a mesma cara do pânico de um motorista, e quem está de
   * plantão pode acionar apoio por causa de um teste.
   */
  origem?: string | null;
  /** Janela da política. Continua no contrato; a tela não mostra mais. */
  decorrido_s: number;
  sla_s: number;
  /** Quando o evento aconteceu — é isto que aparece ao lado de cada item. */
  momento: string | null;
  dia: string | null;
  momento_completo: string | null;
  /** Posição do veículo. A tela ao vivo lê daqui, não da ocorrência. */
  latitude: number | null;
  longitude: number | null;
  endereco: string | null;
  leitura_ia: string | null;
  tratamento_paralelo: string | null;
  tem_detalhe: boolean;
  tem_ao_vivo: boolean;
  /** Conversa real acontecendo agora — sem revelar as falas aos poucos. */
  ao_vivo_real: boolean;
  roteiro: PassoRoteiro[];
  falas: Turno[];
}

export interface Fila {
  precisa_de_voce: ItemFila[];
  ia_esta_fazendo: ItemFila[];
}

export interface EventoAuditoria {
  horario: string;
  descricao: string;
}

export interface Ocorrencia {
  ocorrencia_id: string;
  tipo_evento: string;
  grau: Grau;
  canal: Canal;
  placa: string;
  interlocutor: string;
  telefone: string | null;
  aberta_ha: string;
  /** Posição no momento do evento. `null` = sem mapa, e sem ponto inventado. */
  latitude: number | null;
  longitude: number | null;
  endereco: string | null;
  briefing: string;
  /** O que a IA fez antes de o caso chegar ao humano. Vazio quando não houve nada. */
  handoff: string[];
  /** Chance de o caso ser real, estimada pela triagem. Só em evento crítico. */
  probabilidade_real: number | null;
  acoes: string[];
  conversa: Turno[];
  turnos: number;
  duracao: string;
  ficha: Record<string, string>;
  auditoria: EventoAuditoria[];
  politica_versao: string;
  prompt_versao: string;
}

export interface Encerrada {
  ocorrencia_id: string;
  tipo_evento: string;
  canal: Canal;
  placa: string;
  interlocutor: string;
  desfecho: string;
  encerrada_por: "ia" | "operador";
  /** "IA" ou o nome de quem assinou o fechamento. */
  responsavel: string;
  encerrada_em: string;
  encerrada_dia: string | null;
  duracao: string;
  custo_usd: number | null;
  /** Existe registro completo para abrir — senão a linha não é clicável. */
  tem_detalhe: boolean;
}

export interface Encerrados {
  itens: Encerrada[];
  total_ia: number;
  total_operador: number;
}

/**
 * Contagem aritmética sobre o desfecho registrado pelo operador — sem modelo
 * no caminho. Recall de equipamento é decisão de manutenção, e precisa de
 * número conferível, não de inferência.
 */
export interface EquipamentoReincidente {
  placa: string;
  imei: string;
  cliente: string | null;
  tipo_evento: string;
  ocorrencias_90d: number;
  confirmados_sem_causa: number;
  ultimo_em: string;
  candidato_a_recall: boolean;
  motivo: string;
}

export interface Vital {
  rotulo: string;
  valor: string;
  unidade: string | null;
  nota: string | null;
  bom: boolean;
  selo: string | null;
  /** Para onde o número leva. `null` = não é clicável, e não parece clicável. */
  destino: "recall" | "encerrados" | null;
}

export interface Barra {
  rotulo: string;
  valor: number;
}

export interface Metricas {
  vitais: Vital[];
  contencao_por_hora: number[];
  volume_por_evento: Barra[];
  motivos_de_escalonamento: Barra[];
  total_escalonamentos: number;
}

export interface EstadoIA {
  ia_ativa: boolean;
  modo_voz: string;
  ambiente: string;
  panico_autonomo: boolean;
  fonte_rastreamento: string;
}

export interface Prontidao {
  status: string;
  kill_switch_ativo: boolean;
  modo_voz: string;
  dependencias: Record<string, { ok: boolean; erro?: string }>;
}

export const GRAU_ROTULO: Record<Grau, string> = {
  critica: "Crítica",
  alta: "Alta",
  media: "Média",
  baixa: "Baixa",
};

/**
 * Veículo com alarme suprimido por um período.
 *
 * Não é o mesmo que encerrado: encerrado quer dizer *acabou*, desativado quer
 * dizer *continua acontecendo e é esperado*. Vem dos scripts da Central — doc 23.
 */
/**
 * Um número que pediu para sair dos avisos de um veículo.
 *
 * ⚠️ Não é o mesmo que `Desativado`: lá é o veículo com alarme suprimido por
 * um tempo; aqui é o contato que saiu, e o alarme continua valendo.
 */
export interface NumeroRemovido {
  telefone: string;
  placa: string;
  quando: string;
  ocorrencia_id: string;
  /** A frase do cliente, para o operador julgar se foi pedido ou engano. */
  pedido: string;
}

export interface Desativado {
  ocorrencia_id: string;
  tipo_evento: string;
  placa: string;
  interlocutor: string;
  desfecho: string;
  desativado_em: string;
  /** Hora do fim, ou "até a situação mudar" quando não há prazo. */
  ate: string;
  expirado: boolean;
}

/**
 * O catálogo da tela de eventos de teste.
 *
 * Vem da API inteiro, e é de propósito: o rótulo do evento é casado por
 * **igualdade exata** no servidor, então uma cópia escrita à mão aqui viraria
 * `fora_do_catalogo` no dia em que alguém corrigisse um acento no domínio.
 */
export interface EventoDisponivel {
  codigo: string;
  rotulo: string;
  descricao: string;
  exige_triagem_previa: boolean;
  encerra_sem_operador: boolean;
}

export interface CatalogoDeTeste {
  ativo: boolean;
  ambiente: string;
  eventos: EventoDisponivel[];
  usados_hoje: number;
  teto_por_dia: number;
  modelo_atual: string;
}

export interface PedidoDeTeste {
  tipo: string;
  telefone: string;
  nome?: string;
  placa?: string;
}

/** O que aconteceu com o disparo, dito de um jeito que dispensa ler log. */
export interface ReciboDeTeste {
  aceito: boolean;
  resumo: string;
  motivo: string | null;
  evento_id: string | null;
  ocorrencia_id: string | null;
  disparado_em: string;
  para: string;
  /** Vazio quando ninguém preencheu. A linha some, em vez de ficar sem valor. */
  nome: string;
  placa: string;
  tipo: string;
  rotulo: string;
  modelo: string;
  usados_hoje: number;
  teto_por_dia: number;
  payload: Record<string, unknown>;
}

/** Um modelo de IA que a Central pode escolher, com o defeito dito junto. */
export interface ModeloDisponivel {
  id: string;
  nome: string;
  /** Custo médio por atendimento em reais, **template da Meta incluído**. */
  custo: string;
  /** A conta aberta: quanto é template e quanto é IA. */
  custo_detalhe: string;
  /** Como se compara com o outro. Número sozinho não decide nada. */
  custo_comparativo: string;
  /** Uma linha, ou vazio. Vazio não vira linha em branco no cartão. */
  resumo: string;
  /**
   * "sim" ou "não".
   *
   * Não vira mais selo na tela (tirado a pedido em 03/09/2026); os defeitos que
   * sustentam o "não" continuam no `detalhe`. Fica no contrato como registro da
   * decisão, para quem for consultar por fora do painel.
   */
  aprovado_para_producao: string;
}

export interface EstadoDoModelo {
  atual: string;
  /** Qual escolher e quando mudar de ideia. Vem do servidor, junto da lista. */
  orientacao: string;
  /** A mesma regra em cinco palavras, para o rótulo do retrátil fechado. */
  orientacao_curta: string;
  disponiveis: ModeloDisponivel[];
}
