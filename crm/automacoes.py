"""
Motor de automações por etapa.

Cada etapa do pipeline pode ter automações. Dois gatilhos:

    ao_entrar   — executa no instante em que o lead entra na etapa
    apos_horas  — executa quando o lead completa X horas na etapa

Ações suportadas:
    enviar_mensagem   — dispara uma mensagem pelo canal configurado
    adicionar_tag     — associa uma etiqueta ao lead
    remover_tag       — remove uma etiqueta do lead
    mover_etapa       — move o lead para outra etapa (pode encadear automações)
    criar_tarefa      — cria uma tarefa para o atendente
    parar_sequencia   — pausa o disparo automático da sequência de mensagens

O encadeamento de 'mover_etapa' tem trava de profundidade para nunca entrar
em loop infinito entre etapas.
"""

import logging

from . import db

log = logging.getLogger("crm.automacoes")

PROFUNDIDADE_MAXIMA = 8


def _personalizar(texto: str, lead: dict) -> str:
    nome = (lead.get("nome") or "").strip()
    primeiro = nome.split()[0] if nome else ""
    return (
        (texto or "")
        .replace("{nome}", nome or "tudo bem?")
        .replace("{primeiro_nome}", primeiro or "tudo bem?")
        .replace("{telefone}", lead.get("telefone", ""))
    )


def _executar(lead_id: int, automacao: dict, profundidade: int) -> None:
    lead = db.obter_lead(lead_id)
    if not lead:
        return
    acao = automacao["acao"]

    try:
        if acao == "enviar_mensagem":
            from .channels import obter_canal
            canal = obter_canal()
            texto = _personalizar(automacao.get("texto", ""), lead)
            if not texto.strip():
                return
            resultado = canal.enviar(lead["telefone"], texto)
            db.marcar_envio(lead_id, None, lead["etapa_atual"], texto, canal.nome,
                            resultado.sucesso, "" if resultado.sucesso else resultado.detalhe)
            log.info("Automação enviou mensagem para %s (%s)", lead["telefone"],
                     "ok" if resultado.sucesso else resultado.detalhe)

        elif acao == "adicionar_tag" and automacao.get("tag_id"):
            db.adicionar_tag_lead(lead_id, automacao["tag_id"])

        elif acao == "remover_tag" and automacao.get("tag_id"):
            db.remover_tag_lead(lead_id, automacao["tag_id"])

        elif acao == "criar_tarefa":
            titulo = _personalizar(automacao.get("texto") or "Tarefa automática", lead)
            db.criar_tarefa(lead_id, titulo, origem="automacao")

        elif acao == "parar_sequencia":
            db.atualizar_lead(lead_id, status_funil=db.STATUS_PAUSADO)
            log.info("Automação pausou a sequência do lead %s", lead_id)

        elif acao == "mover_etapa" and automacao.get("etapa_destino"):
            destino = automacao["etapa_destino"]
            if destino == lead["etiqueta"]:
                return  # já está lá, não reprocessa
            if not db.slug_valido(destino):
                log.warning("Automação aponta para etapa inexistente: %s", destino)
                return
            stage = db.stage_por_slug(destino)
            status = stage.get("status_padrao") or db.STATUS_ATIVO
            db.mover_etiqueta(lead_id, destino, status, motivo="(automação)")
            # Encadeia as automações 'ao_entrar' da etapa de destino.
            if profundidade < PROFUNDIDADE_MAXIMA:
                ao_entrar(lead_id, destino, profundidade + 1)
            else:
                log.warning("Profundidade máxima de encadeamento atingida no lead %s", lead_id)

    except Exception:
        log.exception("Erro ao executar automação %s (ação %s)", automacao.get("id"), acao)


def ao_entrar(lead_id: int, slug: str, profundidade: int = 0) -> int:
    """Executa as automações 'ao_entrar' da etapa. Retorna quantas rodaram."""
    automacoes = db.automacoes_por_slug(slug, "ao_entrar")
    for a in automacoes:
        _executar(lead_id, a, profundidade)
    return len(automacoes)


def processar_tempo() -> int:
    """
    Varre os leads e dispara automações 'apos_horas' vencidas na etapa atual.
    Chamado a cada ciclo do worker. Retorna quantas automações rodaram.
    """
    total = 0
    leads = db.leads_para_automacao_tempo()
    agora_dt = db.agora()
    for lead in leads:
        stage_desde = db.ler_data(lead.get("stage_desde")) or db.ler_data(lead.get("criado_em"))
        if not stage_desde:
            continue
        horas_na_etapa = (agora_dt - stage_desde).total_seconds() / 3600
        for a in db.automacoes_por_slug(lead["etiqueta"], "apos_horas"):
            if horas_na_etapa < float(a["horas"]):
                continue
            if db.automacao_ja_executada(lead["id"], a["id"], lead.get("stage_desde")):
                continue
            _executar(lead["id"], a, 0)
            db.marcar_automacao_executada(lead["id"], a["id"])
            total += 1
    return total
