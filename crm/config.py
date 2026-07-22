"""
Configuração central do CRM.

Lê um arquivo .env na raiz do projeto (se existir) sem depender de bibliotecas
externas. Variáveis de ambiente reais têm prioridade sobre o .env.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ENV = RAIZ / ".env"


def _carregar_env(caminho: Path) -> None:
    """Carrega KEY=VALUE de um .env para os.environ (sem sobrescrever o que já existe)."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        os.environ.setdefault(chave, valor)


_carregar_env(ARQUIVO_ENV)


def _texto(chave: str, padrao: str = "") -> str:
    return os.environ.get(chave, padrao).strip()


def _inteiro(chave: str, padrao: int) -> int:
    try:
        return int(os.environ.get(chave, padrao))
    except (TypeError, ValueError):
        return padrao


def _booleano(chave: str, padrao: bool) -> bool:
    valor = os.environ.get(chave)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


# ----------------------------- Banco de dados -----------------------------
CAMINHO_BANCO = _texto("CRM_BANCO", str(RAIZ / "crm_leads.db"))

# ------------------------------- Servidor ---------------------------------
HOST = _texto("CRM_HOST", "127.0.0.1")
PORTA = _inteiro("CRM_PORTA", 8765)

# --------------------------- Canal de envio -------------------------------
# "evolution" (produção, com webhook de resposta) ou "selenium" (WhatsApp Web,
# sem detecção automática de resposta) ou "simulado" (não envia nada, só loga).
CANAL = _texto("CRM_CANAL", "simulado").lower()

EVOLUTION_URL       = _texto("EVOLUTION_URL").rstrip("/")
EVOLUTION_INSTANCIA = _texto("EVOLUTION_INSTANCIA")
EVOLUTION_APIKEY    = _texto("EVOLUTION_APIKEY")
# "v2" (padrão, Evolution API 2.x) ou "v1"
EVOLUTION_VERSAO    = _texto("EVOLUTION_VERSAO", "v2").lower()
# URL pública que a Evolution vai chamar quando chegar mensagem.
# Ex.: https://seu-dominio.com/webhook/evolution  (ou um túnel ngrok/cloudflared)
WEBHOOK_URL_PUBLICA = _texto("CRM_WEBHOOK_URL")
# Token opcional exigido no header X-CRM-Token do webhook (defesa simples).
WEBHOOK_TOKEN       = _texto("CRM_WEBHOOK_TOKEN")

# ------------------------------- Worker -----------------------------------
# De quanto em quanto tempo o worker acorda para verificar leads vencidos.
WORKER_INTERVALO_SEGUNDOS = _inteiro("CRM_WORKER_INTERVALO", 60)
# Tamanho do LOTE: quantas mensagens são enviadas antes da pausa automática.
LOTE_MAXIMO = _inteiro("CRM_LOTE_MAXIMO", 30)
# Pausa automática ENTRE lotes, em minutos. Ao completar um lote cheio, o worker
# espera esse tempo e depois continua do ponto onde parou. 0 = sem pausa entre lotes.
LOTE_PAUSA_MINUTOS = _inteiro("CRM_LOTE_PAUSA_MINUTOS", 10)
# Pausa entre mensagens dentro do mesmo lote, em segundos.
PAUSA_ENTRE_ENVIOS = _inteiro("CRM_PAUSA_ENTRE_ENVIOS", 8)
# Janela de horário permitida para disparo (hora local, 0-23). Fora dela o
# worker não envia nada. Deixe 0 e 24 para liberar o dia inteiro.
JANELA_HORA_INICIO = _inteiro("CRM_JANELA_INICIO", 8)
JANELA_HORA_FIM    = _inteiro("CRM_JANELA_FIM", 20)
# Disparar aos sábados/domingos?
DISPARAR_FIM_DE_SEMANA = _booleano("CRM_FIM_DE_SEMANA", False)
# Worker começa ligado quando o servidor sobe?
WORKER_AUTOSTART = _booleano("CRM_WORKER_AUTOSTART", False)

# ------------------------------- Painel -----------------------------------
# Dias sem resposta a partir dos quais o lead aparece destacado em vermelho.
ALERTA_DIAS = _inteiro("CRM_ALERTA_DIAS", 3)
# DDI padrão aplicado a números sem código de país.
DDI_PADRAO = _texto("CRM_DDI_PADRAO", "55")

# ------------------------------- Chatwoot ---------------------------------
# A API Key nunca fica hardcoded — vem sempre da variável de ambiente.
CHATWOOT_URL        = _texto("CHATWOOT_URL").rstrip("/")
CHATWOOT_ACCOUNT_ID = _texto("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_KEY    = _texto("CHATWOOT_API_KEY")
# Sincronizar automaticamente de tempos em tempos (0 = só sob demanda).
CHATWOOT_SYNC_MINUTOS = _inteiro("CHATWOOT_SYNC_MINUTOS", 0)
# Quantos itens por página nas chamadas de listagem.
CHATWOOT_PAGINA = _inteiro("CHATWOOT_PAGINA", 50)
# Tentativas em caso de falha de rede antes de desistir do item.
CHATWOOT_TENTATIVAS = _inteiro("CHATWOOT_TENTATIVAS", 3)


def chatwoot_configurado() -> bool:
    return bool(CHATWOOT_URL and CHATWOOT_ACCOUNT_ID and CHATWOOT_API_KEY)


def resumo() -> dict:
    """Snapshot da configuração para exibir no painel (sem expor segredos)."""
    return {
        "canal": CANAL,
        "evolution_configurada": bool(EVOLUTION_URL and EVOLUTION_INSTANCIA and EVOLUTION_APIKEY),
        "evolution_url": EVOLUTION_URL,
        "evolution_instancia": EVOLUTION_INSTANCIA,
        "webhook_url": WEBHOOK_URL_PUBLICA,
        "alerta_dias": ALERTA_DIAS,
        "janela": [JANELA_HORA_INICIO, JANELA_HORA_FIM],
        "fim_de_semana": DISPARAR_FIM_DE_SEMANA,
        "worker_intervalo": WORKER_INTERVALO_SEGUNDOS,
        "lote_maximo": LOTE_MAXIMO,
        "lote_pausa_minutos": LOTE_PAUSA_MINUTOS,
        "pausa_entre_envios": PAUSA_ENTRE_ENVIOS,
        "banco": CAMINHO_BANCO,
        "chatwoot_configurado": chatwoot_configurado(),
        "chatwoot_url": CHATWOOT_URL,
        "chatwoot_sync_minutos": CHATWOOT_SYNC_MINUTOS,
    }
