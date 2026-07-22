"""
Canal Evolution API (self-hosted).

Envio: POST {url}/message/sendText/{instancia}  (header: apikey)
Webhook: configurado via POST {url}/webhook/set/{instancia}

Suporta os dois formatos de payload (v2, padrão; v1, legado) — se o v2 for
recusado com 400/404, tenta o v1 automaticamente e memoriza o que funcionou.
"""

import logging

import httpx

from .. import config, db
from .base import Canal, ResultadoEnvio

log = logging.getLogger("crm.canal.evolution")


def _limpar_url(url: str) -> str:
    """Remove barra final e um eventual '/manager' que o usuário cole por engano."""
    u = (url or "").strip().rstrip("/")
    if u.endswith("/manager"):
        u = u[: -len("/manager")]
    return u.rstrip("/")


class CanalEvolution(Canal):
    nome = "evolution"
    recebe_respostas = True

    def __init__(self, url=None, instancia=None, apikey=None, versao=None):
        # Prioridade: argumento > configuração salva no painel (banco) > .env
        self.url = _limpar_url(url or db.obter_config("evolution_url") or config.EVOLUTION_URL)
        self.instancia = instancia or db.obter_config("evolution_instancia") or config.EVOLUTION_INSTANCIA
        self.apikey = apikey or db.obter_config("evolution_apikey") or config.EVOLUTION_APIKEY
        self.versao = (versao or db.obter_config("evolution_versao") or config.EVOLUTION_VERSAO).lower()
        self._cliente = httpx.Client(timeout=30, headers={"apikey": self.apikey})

    # ------------------------------------------------------------------ #
    @property
    def configurada(self) -> bool:
        return bool(self.url and self.instancia and self.apikey)

    def _corpo(self, telefone: str, texto: str, versao: str) -> dict:
        if versao == "v1":
            return {
                "number": telefone,
                "options": {"delay": 1200, "presence": "composing"},
                "textMessage": {"text": texto},
            }
        return {"number": telefone, "text": texto, "delay": 1200}

    # ------------------------------------------------------------------ #
    def enviar(self, telefone: str, texto: str) -> ResultadoEnvio:
        if not self.configurada:
            return ResultadoEnvio(False, "Evolution API não configurada (.env incompleto)")

        endpoint = f"{self.url}/message/sendText/{self.instancia}"
        tentativas = [self.versao] + (["v1"] if self.versao != "v1" else ["v2"])

        ultimo_erro = ""
        for versao in tentativas:
            try:
                resposta = self._cliente.post(endpoint, json=self._corpo(telefone, texto, versao))
            except httpx.HTTPError as e:
                return ResultadoEnvio(False, f"Falha de rede: {e}")

            if resposta.status_code < 300:
                if versao != self.versao:
                    log.info("Payload %s aceito — passando a usar esse formato.", versao)
                    self.versao = versao
                dados = _json_seguro(resposta)
                id_externo = (dados.get("key") or {}).get("id", "") if isinstance(dados, dict) else ""
                return ResultadoEnvio(True, "enviado", id_externo)

            ultimo_erro = f"HTTP {resposta.status_code}: {resposta.text[:200]}"
            if resposta.status_code not in (400, 404, 422):
                break  # 401/500 não é problema de formato — não adianta tentar de novo

        return ResultadoEnvio(False, ultimo_erro or "erro desconhecido")

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        base = {
            "nome": self.nome,
            "pronto": False,
            "detalhe": "",
            "recebe_respostas": True,
            "instancia": self.instancia,
        }
        if not self.configurada:
            base["detalhe"] = "Preencha EVOLUTION_URL, EVOLUTION_INSTANCIA e EVOLUTION_APIKEY no .env"
            return base
        try:
            r = self._cliente.get(f"{self.url}/instance/connectionState/{self.instancia}")
            dados = _json_seguro(r)
            estado = ""
            if isinstance(dados, dict):
                estado = (dados.get("instance") or {}).get("state") or dados.get("state") or ""
            base["pronto"] = estado == "open"
            base["detalhe"] = f"Estado da instância: {estado or r.status_code}"
        except httpx.HTTPError as e:
            base["detalhe"] = f"Não foi possível falar com a Evolution API: {e}"
        return base

    # ------------------------------------------------------------------ #
    def configurar_webhook(self, url_publica: str) -> dict:
        """
        Registra na Evolution o endereço que ela deve chamar quando chegar
        mensagem. Deve ser uma URL acessível pela internet (VPS, ngrok, etc.).
        """
        if not self.configurada:
            return {"ok": False, "detalhe": "Evolution API não configurada"}

        eventos = ["MESSAGES_UPSERT"]
        tentativas = [
            {"webhook": {"enabled": True, "url": url_publica, "webhookByEvents": False,
                         "webhookBase64": False, "events": eventos}},                       # v2
            {"enabled": True, "url": url_publica, "webhook_by_events": False,
             "events": eventos},                                                            # v1
        ]
        endpoint = f"{self.url}/webhook/set/{self.instancia}"
        ultimo = ""
        for corpo in tentativas:
            try:
                r = self._cliente.post(endpoint, json=corpo)
            except httpx.HTTPError as e:
                return {"ok": False, "detalhe": f"Falha de rede: {e}"}
            if r.status_code < 300:
                return {"ok": True, "detalhe": f"Webhook apontado para {url_publica}"}
            ultimo = f"HTTP {r.status_code}: {r.text[:200]}"
        return {"ok": False, "detalhe": ultimo}

    def encerrar(self) -> None:
        try:
            self._cliente.close()
        except Exception:
            pass


def _json_seguro(resposta):
    try:
        return resposta.json()
    except Exception:
        return {}


# =========================== PARSER DO WEBHOOK ==============================

def extrair_mensagem(payload: dict):
    """
    Normaliza o payload de MESSAGES_UPSERT da Evolution.

    Devolve {'telefone', 'texto', 'de_mim', 'grupo', 'nome'} ou None quando o
    evento não é uma mensagem de texto individual recebida.
    """
    if not isinstance(payload, dict):
        return None

    evento = (payload.get("event") or payload.get("Event") or "").lower().replace("_", ".")
    if evento and evento not in ("messages.upsert", "messages.update"):
        return None

    dados = payload.get("data") or payload.get("message") or payload
    if isinstance(dados, list):
        dados = dados[0] if dados else {}
    if not isinstance(dados, dict):
        return None
    # v1 aninha em {"data": {"messages": [...]}}
    if "messages" in dados and isinstance(dados["messages"], list):
        dados = dados["messages"][0] if dados["messages"] else {}

    chave = dados.get("key") or {}
    remote_jid = chave.get("remoteJid") or dados.get("remoteJid") or ""
    if not remote_jid:
        return None

    grupo = remote_jid.endswith("@g.us") or "@broadcast" in remote_jid
    telefone = remote_jid.split("@")[0].split(":")[0]

    return {
        "telefone": telefone,
        "texto": _texto_da_mensagem(dados.get("message") or {}),
        "de_mim": bool(chave.get("fromMe")),
        "grupo": grupo,
        "nome": dados.get("pushName") or "",
    }


def _texto_da_mensagem(mensagem: dict) -> str:
    """Extrai o texto de qualquer um dos formatos de mensagem do WhatsApp."""
    if not isinstance(mensagem, dict):
        return ""
    if mensagem.get("conversation"):
        return mensagem["conversation"]
    for chave in ("extendedTextMessage", "imageMessage", "videoMessage", "documentMessage"):
        bloco = mensagem.get(chave)
        if isinstance(bloco, dict):
            texto = bloco.get("text") or bloco.get("caption")
            if texto:
                return texto
    botao = mensagem.get("buttonsResponseMessage") or mensagem.get("templateButtonReplyMessage")
    if isinstance(botao, dict):
        return botao.get("selectedDisplayText") or botao.get("selectedId") or ""
    lista = mensagem.get("listResponseMessage")
    if isinstance(lista, dict):
        return lista.get("title") or ""

    # Mídia sem legenda ainda é uma resposta ativa: o lead interagiu. Devolvemos
    # um marcador para que a regra de roteamento tire ele do disparo automático.
    marcadores = {
        "audioMessage":    "[áudio recebido]",
        "imageMessage":    "[imagem recebida]",
        "videoMessage":    "[vídeo recebido]",
        "documentMessage": "[documento recebido]",
        "stickerMessage":  "[figurinha recebida]",
        "contactMessage":  "[contato recebido]",
        "locationMessage": "[localização recebida]",
        "reactionMessage": "[reação recebida]",
    }
    for chave, marcador in marcadores.items():
        if chave in mensagem:
            return marcador
    return ""
