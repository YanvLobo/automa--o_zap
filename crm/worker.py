"""
Worker do funil automático.

A cada ciclo (padrão: 60s) o worker:
    1. busca leads com status_funil = 'ativo';
    2. verifica se o intervalo do próximo passo já venceu;
    3. envia a mensagem pelo canal configurado;
    4. avança etapa_atual e grava ultima_mensagem_enviada_em.

Leads que respondem saem do funil pelo webhook (crm/regras.py), então o worker
nunca dispara "por cima" de um atendimento humano.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from . import automacoes, config, db
from .channels import obter_canal

log = logging.getLogger("crm.worker")

_scheduler = None
_lock = threading.Lock()
_ultimo_ciclo = {"em": None, "enviados": 0, "falhas": 0, "detalhe": "worker nunca executou"}
# Momento (datetime) em que a pausa entre lotes termina. None = sem pausa ativa.
_pausa_lote_ate = None
# Já registramos o webhook da Evolution neste processo?
_webhook_ok = False


def resetar_webhook():
    """Faz o worker tentar registrar o webhook de novo (após mudar a config)."""
    global _webhook_ok
    _webhook_ok = False


def _garantir_webhook_evolution():
    """
    Registra o webhook na Evolution automaticamente, sem precisar de terminal.
    Tenta a cada ciclo até dar certo (a instância pode ainda não estar conectada).
    """
    global _webhook_ok
    if _webhook_ok:
        return
    if config.CANAL != "evolution":
        return
    url_webhook = db.obter_config("webhook_url") or config.WEBHOOK_URL_PUBLICA
    if not url_webhook:
        return
    try:
        canal = obter_canal()
        if hasattr(canal, "configurar_webhook"):
            resultado = canal.configurar_webhook(url_webhook)
            if resultado.get("ok"):
                _webhook_ok = True
                log.info("Webhook da Evolution registrado automaticamente em %s", url_webhook)
    except Exception:
        log.debug("Webhook ainda não registrado (instância pode não estar conectada).")


# ============================ JANELA DE HORÁRIO =============================

def dentro_da_janela(momento=None):
    """(permitido, motivo) — respeita horário comercial e fim de semana."""
    momento = momento or datetime.now()
    if not config.DISPARAR_FIM_DE_SEMANA and momento.weekday() >= 5:
        return False, "fim de semana (desativado na configuração)"
    inicio, fim = config.JANELA_HORA_INICIO, config.JANELA_HORA_FIM
    if inicio == 0 and fim >= 24:
        return True, ""
    if not (inicio <= momento.hour < fim):
        return False, f"fora da janela de disparo ({inicio}h–{fim}h)"
    return True, ""


# ================================= CICLO ====================================

def personalizar(texto: str, lead: dict) -> str:
    """Substitui as variáveis disponíveis no texto do passo."""
    nome = (lead.get("nome") or "").strip()
    primeiro = nome.split()[0] if nome else ""
    return (
        texto.replace("{nome}", nome or "tudo bem?")
             .replace("{primeiro_nome}", primeiro or "tudo bem?")
             .replace("{telefone}", lead.get("telefone", ""))
    )


def executar_ciclo(forcar=False) -> dict:
    """
    Roda um ciclo de disparo. `forcar=True` ignora a janela de horário e a
    pausa entre lotes (usado pelo botão "Disparar agora" do painel).

    Controle de lote: envia no máximo LOTE_MAXIMO mensagens por ciclo. Se o lote
    encher (havia mais leads esperando), agenda uma pausa automática de
    LOTE_PAUSA_MINUTOS antes do próximo lote — e retoma sozinho de onde parou.
    """
    global _ultimo_ciclo, _pausa_lote_ate

    permitido, motivo = dentro_da_janela()
    if not permitido and not forcar:
        _ultimo_ciclo = {"em": db.agora_iso(), "enviados": 0, "falhas": 0, "detalhe": motivo}
        return _ultimo_ciclo

    # Pausa entre lotes: se ainda estamos dentro dela, não envia nada.
    agora_dt = datetime.now()
    if _pausa_lote_ate and agora_dt < _pausa_lote_ate and not forcar:
        restante = int((_pausa_lote_ate - agora_dt).total_seconds())
        _ultimo_ciclo = {"em": db.agora_iso(), "enviados": 0, "falhas": 0,
                         "detalhe": f"em pausa entre lotes — retoma em {restante // 60}min{restante % 60:02d}s",
                         "pausa_lote_ate": _pausa_lote_ate.isoformat()}
        return _ultimo_ciclo
    if _pausa_lote_ate and agora_dt >= _pausa_lote_ate:
        _pausa_lote_ate = None  # pausa terminou; retoma o próximo lote

    # Auto-configura o webhook da Evolution assim que a instância estiver pronta.
    _garantir_webhook_evolution()

    # Automações "após X horas na etapa" — independentes da sequência de disparo.
    automacoes_rodadas = 0
    try:
        automacoes_rodadas = automacoes.processar_tempo()
    except Exception:
        log.exception("Erro ao processar automações por tempo")

    canal = obter_canal()
    prontos = db.leads_prontos_para_disparo(config.LOTE_MAXIMO)
    if not prontos:
        _ultimo_ciclo = {"em": db.agora_iso(), "enviados": 0, "falhas": 0,
                         "automacoes": automacoes_rodadas,
                         "detalhe": (f"{automacoes_rodadas} automação(ões) executada(s)"
                                     if automacoes_rodadas else "nenhum lead vencido neste ciclo")}
        return _ultimo_ciclo

    enviados = falhas = 0
    for indice, lead in enumerate(prontos):
        passo = lead["passo"]
        texto = personalizar(passo["texto"], lead)

        resultado = canal.enviar(lead["telefone"], texto)
        db.marcar_envio(
            lead_id=lead["id"],
            sequencia_id=lead["sequencia_id"],
            passo_ordem=passo["ordem"],
            texto=texto,
            canal=canal.nome,
            sucesso=resultado.sucesso,
            erro="" if resultado.sucesso else resultado.detalhe,
        )
        if resultado.sucesso:
            enviados += 1
            log.info("Enviado passo %s para %s (%s)", passo["ordem"], lead["nome"], lead["telefone"])
        else:
            falhas += 1
            log.warning("Falha para %s: %s", lead["telefone"], resultado.detalhe)

        # Espaçamento humano entre mensagens do mesmo lote.
        if indice < len(prontos) - 1 and config.PAUSA_ENTRE_ENVIOS > 0:
            time.sleep(config.PAUSA_ENTRE_ENVIOS)

    # Lote cheio (havia pelo menos LOTE_MAXIMO leads esperando) → pausa e retoma
    # sozinho depois. Só no modo automático; "Disparar agora" não agenda pausa.
    pausou = ""
    if (not forcar and config.LOTE_PAUSA_MINUTOS > 0
            and len(prontos) >= config.LOTE_MAXIMO):
        _pausa_lote_ate = datetime.now() + timedelta(minutes=config.LOTE_PAUSA_MINUTOS)
        pausou = (f" · lote cheio ({config.LOTE_MAXIMO}) — pausa de "
                  f"{config.LOTE_PAUSA_MINUTOS}min antes do próximo")
        log.info("Lote de %s enviado. Pausa de %s min até o próximo lote.",
                 config.LOTE_MAXIMO, config.LOTE_PAUSA_MINUTOS)

    _ultimo_ciclo = {
        "em": db.agora_iso(),
        "enviados": enviados,
        "falhas": falhas,
        "automacoes": automacoes_rodadas,
        "pausa_lote_ate": _pausa_lote_ate.isoformat() if _pausa_lote_ate else None,
        "detalhe": f"{enviados} enviada(s), {falhas} falha(s) via canal '{canal.nome}'"
                   + (f", {automacoes_rodadas} automação(ões)" if automacoes_rodadas else "")
                   + pausou,
    }
    return _ultimo_ciclo


def _job():
    try:
        executar_ciclo()
    except Exception:
        log.exception("Erro no ciclo do worker")


# =============================== CONTROLE ===================================

def iniciar() -> dict:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            return estado()
        _scheduler = BackgroundScheduler(timezone=None)
        _scheduler.add_job(
            _job,
            "interval",
            seconds=config.WORKER_INTERVALO_SEGUNDOS,
            id="ciclo_disparo",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        _scheduler.start()
        log.info("Worker iniciado (ciclo a cada %ss).", config.WORKER_INTERVALO_SEGUNDOS)
    return estado()


def parar() -> dict:
    global _scheduler, _pausa_lote_ate
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            log.info("Worker parado.")
        _scheduler = None
        _pausa_lote_ate = None  # zera a pausa de lote ao desligar
    return estado()


def rodando() -> bool:
    return bool(_scheduler and _scheduler.running)


def estado() -> dict:
    permitido, motivo = dentro_da_janela()
    proxima = None
    if rodando():
        jobs = _scheduler.get_jobs()
        if jobs and jobs[0].next_run_time:
            proxima = jobs[0].next_run_time.isoformat()
    em_pausa = bool(_pausa_lote_ate and datetime.now() < _pausa_lote_ate)
    return {
        "rodando": rodando(),
        "proxima_execucao": proxima,
        "intervalo_segundos": config.WORKER_INTERVALO_SEGUNDOS,
        "dentro_da_janela": permitido,
        "motivo_janela": motivo,
        "lote_maximo": config.LOTE_MAXIMO,
        "lote_pausa_minutos": config.LOTE_PAUSA_MINUTOS,
        "em_pausa_lote": em_pausa,
        "pausa_lote_ate": _pausa_lote_ate.isoformat() if _pausa_lote_ate else None,
        "ultimo_ciclo": _ultimo_ciclo,
    }
