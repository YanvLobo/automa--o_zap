"""
Regras de negócio aplicadas quando chega uma resposta do lead.

    Resposta com padrão de opt-out
        -> etiqueta "Não perturbe" + status_funil = removido (nunca mais dispara)

    Qualquer outra resposta
        -> etiqueta "Respondeu — atendimento manual" + status_funil = pausado
           (o robô sai de cena; o humano assume a conversa)
"""

import logging

from . import db, optout

log = logging.getLogger("crm.regras")


def processar_resposta(telefone: str, texto: str, nome_contato: str = "") -> dict:
    """
    Aplica as regras a uma mensagem recebida.

    Retorna um dict com o que aconteceu. Se o telefone não estiver na base,
    o lead é criado fora do funil (status 'removido' ou 'pausado' conforme a
    regra) — assim nada dispara para quem nunca foi prospectado por aqui.
    """
    telefone_normalizado = db.normalizar_telefone(telefone)
    if not telefone_normalizado:
        return {"acao": "ignorado", "motivo": "telefone inválido"}

    lead = db.obter_lead_por_telefone(telefone_normalizado)
    optout_detectado, padrao = optout.eh_optout(texto)

    # Resolve as etapas pelo papel — assim funciona mesmo se o usuário renomeou
    # as etapas de sistema no pipeline personalizado.
    if optout_detectado:
        stage = db.stage_por_papel("optout")
        etiqueta = stage["slug"] if stage else db.ETIQUETA_OPTOUT
        status = (stage or {}).get("status_padrao") or db.STATUS_REMOVIDO
        motivo = f"opt-out detectado (padrão: '{padrao}')"
        acao = "optout"
    else:
        stage = db.stage_por_papel("respondeu")
        etiqueta = stage["slug"] if stage else db.ETIQUETA_RESPONDEU
        status = (stage or {}).get("status_padrao") or db.STATUS_PAUSADO
        motivo = "resposta ativa — encaminhado para atendimento manual"
        acao = "respondeu"

    if not lead:
        lead = db.criar_lead(
            nome=nome_contato,
            telefone=telefone_normalizado,
            etiqueta=etiqueta,
            status=status,
            observacoes="Criado a partir de uma mensagem recebida.",
        )
        novo = True
    else:
        novo = False

    lead = db.registrar_resposta(lead["id"], texto, etiqueta, status, motivo)
    log.info("Resposta de %s: %s", telefone_normalizado, motivo)

    return {
        "acao": acao,
        "motivo": motivo,
        "lead_criado": novo,
        "lead": lead,
    }
