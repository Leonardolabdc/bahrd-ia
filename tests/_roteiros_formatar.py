"""Lê as linhas JSON do executor e imprime as conversas em markdown."""
import json
import sys

for linha in sys.stdin:
    linha = linha.strip()
    if not linha.startswith("{"):
        continue
    r = json.loads(linha)
    if "erro" in r:
        print(f"\n### {r['id']} · {r['titulo']}\n\nFALHOU: {r['erro']}")
        continue
    print(f"\n### {r['id']} · {r['titulo']}")
    print(f"[desfecho={r['desfecho']} motivo={r['motivo_encerramento']} "
          f"encerrada={r['encerrada']} escalada={r['escalada']} "
          f"turnos={r['turnos_ia']} custo={r['custo_usd']}]")
    for f in r["conversa"]:
        if f["tipo"] == "template":
            print("  IA (template) + botoes")
            continue
        quem = "IA " if f["quem"] == "ia" else "CLI"
        texto = " ".join(f["texto"].split())
        bot = f" [botoes: {', '.join(f['botoes'])}]" if f["botoes"] else ""
        print(f"  {quem}: {texto}{bot}")
    for tr in r["tratativas"]:
        print(f"  >> tratativa: {tr['acao']}")
    for p in r["trilha"]:
        if p.startswith(("SEGURANCA", "SEGURANÇA", "IA: Escalonamento", "SISTEMA: <b>Sem operador",
                         "CLIENTE: <b>Pediu")):
            print(f"  >> trilha: {' '.join(p.split())}")
