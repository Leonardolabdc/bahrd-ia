"""Orquestração — máquina de estados, SLA, cascata de canais e handoff.

Não conversa e não decide elegibilidade. Conduz: chama a política, aciona o
agente quando autorizado, e registra cada passo na trilha de auditoria.
"""
