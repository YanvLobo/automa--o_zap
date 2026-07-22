"""
Integração com o Chatwoot (API oficial de Application/Agent Bot).

Sincroniza, de forma incremental e sem duplicar:
    contatos    -> leads (dedup por chatwoot_contact_id, senão por telefone)
    conversas   -> vínculo lead <-> conversa + status
    mensagens   -> tabela mensagens (dedup por chatwoot_msg_id)
    etiquetas   -> tags (labels do Chatwoot viram tags do lead)

A API Key vem SEMPRE da variável de ambiente CHATWOOT_API_KEY (config.py).
Nada é hardcoded.

Docs: https://www.chatwoot.com/developers/api/
Endpoints usados (v1):
    GET /api/v1/accounts/{acc}/contacts?page=N
    GET /api/v1/accounts/{acc}/conversations?page=N
    GET /api/v1/accounts/{acc}/conversations/{id}/messages
    GET /api/v1/accounts/{acc}/conversations/{id}/labels
"""

import logging
import time

import httpx

from . import config, db, regras

log = logging.getLogger("crm.chatwoot")


class ChatwootErro(Exception):
    pass


class ChatwootCliente:
    def __init__(self, url=None, conta=None, apikey=None):
        self.url = (url or config.CHATWOOT_URL).rstrip("/")
        self.conta = conta or config.CHATWOOT_ACCOUNT_ID
        self.apikey = apikey or config.CHATWOOT_API_KEY
        self._cliente = httpx.Client(
            timeout=30,
            headers={"api_access_token": self.apikey, "Content-Type": "application/json"},
        )

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.conta and self.apikey)

    def _base(self) -> str:
        return f"{self.url}/api/v1/accounts/{self.conta}"

    # ------------------------------------------------------------------ #
    def _get(self, caminho: str, params=None):
        """GET com retry/backoff simples para sobreviver a instabilidade de rede."""
        url = f"{self._base()}{caminho}"
        ultimo = None
        for tentativa in range(1, config.CHATWOOT_TENTATIVAS + 1):
            try:
                r = self._cliente.get(url, params=params)
            except httpx.HTTPError as e:
                ultimo = e
                espera = min(2 ** tentativa, 10)
                log.warning("Falha de rede em %s (tentativa %s/%s): %s — aguardando %ss",
                            caminho, tentativa, config.CHATWOOT_TENTATIVAS, e, espera)
                time.sleep(espera)
                continue
            if r.status_code == 429:  # rate limit
                espera = min(2 ** tentativa, 15)
                log.warning("Rate limit do Chatwoot em %s — aguardando %ss", caminho, espera)
                time.sleep(espera)
                continue
            if r.status_code >= 400:
                raise ChatwootErro(f"HTTP {r.status_code} em {caminho}: {r.text[:200]}")
            try:
                return r.json()
            except Exception as e:
                raise ChatwootErro(f"Resposta não-JSON em {caminho}: {e}")
        raise ChatwootErro(f"Sem resposta de {caminho} após {config.CHATWOOT_TENTATIVAS} tentativas: {ultimo}")

    def testar(self) -> dict:
        if not self.configurado:
            return {"ok": False, "detalhe": "CHATWOOT_URL, CHATWOOT_ACCOUNT_ID e CHATWOOT_API_KEY são obrigatórios"}
        try:
            self._get("/contacts", params={"page": 1})
            return {"ok": True, "detalhe": f"Conectado à conta {self.conta}"}
        except ChatwootErro as e:
            return {"ok": False, "detalhe": str(e)}

    # ------------------------------------------------------------------ #
    def contatos(self, pagina: int):
        return self._get("/contacts", params={"page": pagina})

    def conversas(self, pagina: int):
        return self._get("/conversations", params={"page": pagina, "status": "all"})

    def mensagens(self, conversa_id: int):
        return self._get(f"/conversations/{conversa_id}/messages")

    def encerrar(self):
        try:
            self._cliente.close()
        except Exception:
            pass


# ============================ NORMALIZAÇÃO =================================

def _telefone_do_contato(contato: dict) -> str:
    tel = contato.get("phone_number") or ""
    if not tel:
        for ci in contato.get("contact_inboxes", []) or []:
            if ci.get("source_id"):
                tel = ci["source_id"]
                break
    return db.normalizar_telefone(tel)


def _lista(resposta):
    """O Chatwoot ora devolve {'payload': [...]}, ora {'data': {'payload': [...]}}."""
    if isinstance(resposta, dict):
        if isinstance(resposta.get("payload"), list):
            return resposta["payload"]
        dados = resposta.get("data")
        if isinstance(dados, dict) and isinstance(dados.get("payload"), list):
            return dados["payload"]
        if isinstance(dados, list):
            return dados
    if isinstance(resposta, list):
        return resposta
    return []


# =============================== SYNC ======================================

def sincronizar(cliente: ChatwootCliente = None, max_paginas=20) -> dict:
    """
    Roda uma sincronização incremental. Devolve um resumo com contadores.
    Seguro para rodar repetidamente: nada é duplicado.
    """
    cliente = cliente or ChatwootCliente()
    if not cliente.configurado:
        return {"ok": False, "detalhe": "Chatwoot não configurado (.env incompleto)"}

    resumo = {"ok": True, "contatos": 0, "leads_novos": 0, "conversas": 0,
              "mensagens": 0, "tags": 0, "erros": 0, "detalhe": ""}

    try:
        _sync_contatos(cliente, resumo, max_paginas)
        _sync_conversas(cliente, resumo, max_paginas)
    except ChatwootErro as e:
        resumo["ok"] = False
        resumo["detalhe"] = str(e)
        log.error("Sync interrompido: %s", e)
    finally:
        db.salvar_sync("chatwoot:ultimo_run", db.agora_iso())

    resumo["detalhe"] = resumo["detalhe"] or (
        f"{resumo['leads_novos']} lead(s) novo(s), {resumo['mensagens']} mensagem(ns), "
        f"{resumo['tags']} etiqueta(s)."
    )
    log.info("Sync Chatwoot: %s", resumo["detalhe"])
    return resumo


def _sync_contatos(cliente, resumo, max_paginas):
    pagina = 1
    while pagina <= max_paginas:
        contatos = _lista(cliente.contatos(pagina))
        if not contatos:
            break
        for contato in contatos:
            resumo["contatos"] += 1
            try:
                _upsert_contato(contato, resumo)
            except Exception:
                resumo["erros"] += 1
                log.exception("Falha ao importar contato %s", contato.get("id"))
        pagina += 1


def _upsert_contato(contato: dict, resumo: dict):
    cid = contato.get("id")
    nome = contato.get("name") or ""
    telefone = _telefone_do_contato(contato)

    lead = db.lead_por_chatwoot(cid) if cid else None
    if not lead and telefone:
        lead = db.obter_lead_por_telefone(telefone)

    if not lead:
        if not telefone:
            return  # sem telefone não dá para prospectar; ignora
        lead = db.criar_lead(
            nome=nome, telefone=telefone,
            etiqueta=db.ETIQUETA_RESPONDEU,   # veio do atendimento, não do funil frio
            status=db.STATUS_PAUSADO,
            observacoes="Importado do Chatwoot.",
            chatwoot_contact_id=cid,
        )
        resumo["leads_novos"] += 1
    else:
        # Enriquece sem sobrescrever à toa e garante o vínculo.
        campos = {}
        if nome and not lead.get("nome"):
            campos["nome"] = nome
        if campos:
            db.atualizar_lead(lead["id"], **campos)
        if cid and not lead.get("chatwoot_contact_id"):
            db.vincular_chatwoot(lead["id"], contact_id=cid)

    # Etiquetas do contato -> tags
    for rotulo in contato.get("labels", []) or []:
        tag = db.tag_por_nome(str(rotulo))
        db.adicionar_tag_lead(lead["id"], tag["id"])
        resumo["tags"] += 1


def _sync_conversas(cliente, resumo, max_paginas):
    pagina = 1
    while pagina <= max_paginas:
        conversas = _lista(cliente.conversas(pagina))
        if not conversas:
            break
        for conversa in conversas:
            resumo["conversas"] += 1
            try:
                _sync_uma_conversa(cliente, conversa, resumo)
            except Exception:
                resumo["erros"] += 1
                log.exception("Falha ao importar conversa %s", conversa.get("id"))
        pagina += 1


def _sync_uma_conversa(cliente, conversa, resumo):
    conv_id = conversa.get("id")
    meta = conversa.get("meta") or {}
    contato = meta.get("sender") or {}
    cid = contato.get("id")
    telefone = _telefone_do_contato(contato)

    lead = None
    if cid:
        lead = db.lead_por_chatwoot(cid)
    if not lead and telefone:
        lead = db.obter_lead_por_telefone(telefone)
    if not lead:
        if not telefone:
            return
        lead = db.criar_lead(nome=contato.get("name") or "", telefone=telefone,
                             etiqueta=db.ETIQUETA_RESPONDEU, status=db.STATUS_PAUSADO,
                             observacoes="Importado do Chatwoot (conversa).",
                             chatwoot_contact_id=cid)
        resumo["leads_novos"] += 1

    db.vincular_chatwoot(lead["id"], contact_id=cid, conversation_id=conv_id)

    # Labels da conversa -> tags
    for rotulo in conversa.get("labels", []) or []:
        tag = db.tag_por_nome(str(rotulo))
        db.adicionar_tag_lead(lead["id"], tag["id"])
        resumo["tags"] += 1

    _sync_mensagens(cliente, lead, conv_id, resumo)


def _sync_mensagens(cliente, lead, conv_id, resumo):
    mensagens = _lista(cliente.mensagens(conv_id))
    ultima_entrada = None
    for msg in mensagens:
        mid = msg.get("id")
        conteudo = (msg.get("content") or "").strip()
        # message_type: 0=incoming (lead), 1=outgoing (atendente), 2=activity
        tipo = msg.get("message_type")
        if tipo == 2 or not conteudo or mid is None:
            continue
        direcao = "entrada" if tipo == 0 else "saida"
        criado = msg.get("created_at")
        criado_iso = None
        if isinstance(criado, (int, float)):
            criado_iso = db.datetime.fromtimestamp(criado, db.timezone.utc).isoformat()
        if db.importar_mensagem_chatwoot(lead["id"], mid, direcao, conteudo, criado_iso):
            resumo["mensagens"] += 1
            if direcao == "entrada":
                ultima_entrada = conteudo

    # Se o lead respondeu no Chatwoot, aplica as mesmas regras do funil
    # (opt-out sai; resposta ativa vira atendimento manual e pausa o disparo).
    if ultima_entrada:
        try:
            regras.processar_resposta(lead["telefone"], ultima_entrada, lead.get("nome", ""))
        except Exception:
            log.exception("Falha ao aplicar regras à resposta importada do lead %s", lead["id"])


# =============================== STATUS ====================================

def status() -> dict:
    cliente = ChatwootCliente()
    base = {
        "configurado": cliente.configurado,
        "url": cliente.url,
        "conta": cliente.conta,
        "ultimo_run": db.obter_sync("chatwoot:ultimo_run"),
    }
    if cliente.configurado:
        base.update(cliente.testar())
    else:
        base["ok"] = False
        base["detalhe"] = "Defina CHATWOOT_URL, CHATWOOT_ACCOUNT_ID e CHATWOOT_API_KEY no .env"
    cliente.encerrar()
    return base
