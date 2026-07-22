"""
API + painel do CRM (FastAPI).

Rotas principais:
    GET  /                       painel web (Kanban)
    GET  /api/leads              lista de leads (com alerta_esfriando calculado)
    POST /api/leads              cria lead (ou vários, via importação em massa)
    PATCH/DELETE /api/leads/{id}
    GET  /api/sequencias  POST /api/sequencias  DELETE /api/sequencias/{id}
    POST /api/worker/iniciar | /parar | /ciclo
    POST /webhook/evolution      recebimento de mensagens (regras automáticas)
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import chatwoot, config, db, optout, regras, worker
from .channels import evolution as evo
from .channels import limpar_cache, obter_canal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crm.api")

ESTATICOS = Path(__file__).parent / "static"

_sync_scheduler = None


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    global _sync_scheduler
    db.inicializar()
    log.info("Banco pronto em %s", config.CAMINHO_BANCO)
    if config.WORKER_AUTOSTART:
        worker.iniciar()
        log.info("Worker iniciado automaticamente (CRM_WORKER_AUTOSTART=1).")

    # Sincronização periódica com o Chatwoot (opcional).
    if config.chatwoot_configurado() and config.CHATWOOT_SYNC_MINUTOS > 0:
        from apscheduler.schedulers.background import BackgroundScheduler
        _sync_scheduler = BackgroundScheduler(timezone=None)
        _sync_scheduler.add_job(
            lambda: chatwoot.sincronizar(), "interval",
            minutes=config.CHATWOOT_SYNC_MINUTOS, id="chatwoot_sync",
            max_instances=1, coalesce=True,
        )
        _sync_scheduler.start()
        log.info("Sync do Chatwoot agendado a cada %s min.", config.CHATWOOT_SYNC_MINUTOS)

    yield

    worker.parar()
    if _sync_scheduler:
        _sync_scheduler.shutdown(wait=False)


app = FastAPI(title="VirtualZap CRM", version="1.0.0",
              docs_url="/api/docs", lifespan=ciclo_de_vida)


# ================================= PAINEL ===================================

app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")


@app.get("/", include_in_schema=False)
def painel():
    return FileResponse(ESTATICOS / "painel.html")


# ================================== LEADS ===================================

@app.get("/api/leads")
def api_listar_leads(etiqueta: str = None, status: str = None, busca: str = None,
                     tags: str = None, modo_tags: str = "ou"):
    lista_tags = [int(t) for t in tags.split(",") if t.strip().isdigit()] if tags else None
    stages = db.listar_stages()
    return {
        "leads": db.listar_leads(etiqueta=etiqueta, status=status, busca=busca,
                                 tags=lista_tags, modo_tags=modo_tags),
        "stages": stages,
        "etiquetas": {s["slug"]: s["nome"] for s in stages},
        "tags": db.listar_tags(),
        "status_funil": db.STATUS_FUNIL,
        "alerta_dias": config.ALERTA_DIAS,
    }


@app.post("/api/leads")
def api_criar_leads(corpo: dict = Body(...)):
    """
    Aceita um lead único {nome, telefone, sequencia_id} ou importação em massa:
    {"texto": "Nome|5571999999999\\n5571888888888", "sequencia_id": 1}
    """
    sequencia_id = corpo.get("sequencia_id")
    criados, duplicados, invalidos = [], [], []

    entradas = []
    if corpo.get("texto"):
        for linha in corpo["texto"].splitlines():
            linha = linha.strip()
            if not linha:
                continue
            if "|" in linha:
                nome, telefone = linha.split("|", 1)
            elif ";" in linha:
                nome, telefone = linha.split(";", 1)
            elif "," in linha:
                nome, telefone = linha.split(",", 1)
            else:
                nome, telefone = "", linha
            entradas.append((nome.strip(), telefone.strip()))
    else:
        entradas.append((corpo.get("nome", ""), corpo.get("telefone", "")))

    for nome, telefone in entradas:
        try:
            lead = db.criar_lead(nome=nome, telefone=telefone, sequencia_id=sequencia_id)
        except ValueError:
            invalidos.append(telefone)
            continue
        (duplicados if lead.get("ja_existia") else criados).append(lead)

    return {
        "criados": len(criados),
        "duplicados": len(duplicados),
        "invalidos": invalidos,
        "leads": criados,
    }


@app.patch("/api/leads/{lead_id}")
def api_atualizar_lead(lead_id: int, corpo: dict = Body(...)):
    if not db.obter_lead(lead_id):
        raise HTTPException(404, "Lead não encontrado")
    return db.atualizar_lead(lead_id, **corpo)


@app.delete("/api/leads/{lead_id}")
def api_remover_lead(lead_id: int):
    db.remover_lead(lead_id)
    return {"ok": True}


@app.get("/api/leads/{lead_id}/historico")
def api_historico(lead_id: int):
    if not db.obter_lead(lead_id):
        raise HTTPException(404, "Lead não encontrado")
    return db.historico_lead(lead_id)


@app.post("/api/leads/{lead_id}/etiqueta")
def api_mover_etiqueta(lead_id: int, corpo: dict = Body(...)):
    """
    Move o lead de coluna no Kanban. O status do funil acompanha a etiqueta,
    a não ser que venha explícito no corpo — é a mesma regra do automático,
    só que acionada pela mão do operador.
    """
    etiqueta = corpo.get("etiqueta")
    stage = db.stage_por_slug(etiqueta) if etiqueta else None
    if not stage:
        raise HTTPException(400, f"Etapa inválida: {etiqueta}")

    status = corpo.get("status_funil") or stage.get("status_padrao") or db.STATUS_ATIVO
    return db.mover_etiqueta(lead_id, etiqueta, status, motivo="(manual, pelo painel)")


@app.post("/api/leads/{lead_id}/reativar")
def api_reativar(lead_id: int, corpo: dict = Body(default={})):
    """Devolve o lead ao funil automático, opcionalmente reiniciando a sequência."""
    lead = db.obter_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead não encontrado")
    if lead["etiqueta"] == db.ETIQUETA_OPTOUT and not corpo.get("forcar"):
        raise HTTPException(
            409,
            "Este lead pediu para não receber mais mensagens. "
            "Reative apenas com autorização explícita dele (envie forcar=true).",
        )
    campos = {"status_funil": db.STATUS_ATIVO, "etiqueta": db.ETIQUETA_AGUARDANDO}
    if corpo.get("reiniciar"):
        campos["etapa_atual"] = 0
    if corpo.get("sequencia_id"):
        campos["sequencia_id"] = corpo["sequencia_id"]
    return db.atualizar_lead(lead_id, **campos)


# =============================== SEQUÊNCIAS =================================

@app.get("/api/sequencias")
def api_listar_sequencias():
    return {"sequencias": db.listar_sequencias()}


@app.post("/api/sequencias")
def api_salvar_sequencia(corpo: dict = Body(...)):
    return db.salvar_sequencia(
        sequencia_id=corpo.get("id"),
        nome=corpo.get("nome", "Sem nome"),
        descricao=corpo.get("descricao", ""),
        passos=corpo.get("passos", []),
        ativa=corpo.get("ativa", True),
    )


@app.delete("/api/sequencias/{sequencia_id}")
def api_remover_sequencia(sequencia_id: int):
    db.remover_sequencia(sequencia_id)
    return {"ok": True}


# ============================ ETAPAS (PIPELINE) ============================

@app.get("/api/stages")
def api_listar_stages():
    return {"stages": db.listar_stages()}


@app.post("/api/stages")
def api_salvar_stage(corpo: dict = Body(...)):
    nome = (corpo.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Informe o nome da etapa")
    return db.salvar_stage(
        stage_id=corpo.get("id"),
        nome=nome,
        cor=corpo.get("cor", "#5aa9ff"),
        status_padrao=corpo.get("status_padrao", db.STATUS_ATIVO),
    )


@app.post("/api/stages/reordenar")
def api_reordenar_stages(corpo: dict = Body(...)):
    ids = corpo.get("ids") or []
    return {"stages": db.reordenar_stages(ids)}


@app.delete("/api/stages/{stage_id}")
def api_remover_stage(stage_id: int):
    r = db.remover_stage(stage_id)
    if not r["ok"]:
        raise HTTPException(400, r["erro"])
    return r


# ================================== TAGS ===================================

@app.get("/api/tags")
def api_listar_tags():
    return {"tags": db.listar_tags()}


@app.post("/api/tags")
def api_salvar_tag(corpo: dict = Body(...)):
    nome = (corpo.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Informe o nome da etiqueta")
    return db.salvar_tag(corpo.get("id"), nome, corpo.get("cor", "#e5252e"))


@app.delete("/api/tags/{tag_id}")
def api_remover_tag(tag_id: int):
    db.remover_tag(tag_id)
    return {"ok": True}


@app.post("/api/leads/{lead_id}/tags")
def api_tags_do_lead(lead_id: int, corpo: dict = Body(...)):
    """Define, adiciona ou remove tags de um lead.
    Corpo: {"tag_ids": [...]} substitui tudo; {"adicionar": id} ou {"remover": id}."""
    if not db.obter_lead(lead_id):
        raise HTTPException(404, "Lead não encontrado")
    if "tag_ids" in corpo:
        db.definir_tags_lead(lead_id, corpo["tag_ids"])
    if corpo.get("adicionar"):
        db.adicionar_tag_lead(lead_id, corpo["adicionar"])
    if corpo.get("remover"):
        db.remover_tag_lead(lead_id, corpo["remover"])
    return db.obter_lead(lead_id)


# ============================== AUTOMAÇÕES =================================

@app.get("/api/automacoes")
def api_listar_automacoes(stage_id: int = None):
    return {"automacoes": db.listar_automacoes(stage_id)}


@app.post("/api/automacoes")
def api_salvar_automacao(corpo: dict = Body(...)):
    if not corpo.get("stage_id") or not corpo.get("acao"):
        raise HTTPException(400, "stage_id e acao são obrigatórios")
    return db.salvar_automacao(corpo)


@app.delete("/api/automacoes/{automation_id}")
def api_remover_automacao(automation_id: int):
    db.remover_automacao(automation_id)
    return {"ok": True}


# ================================ TAREFAS ==================================

@app.get("/api/tarefas")
def api_listar_tarefas(pendentes: bool = False):
    return {"tarefas": db.listar_tarefas(apenas_pendentes=pendentes)}


@app.post("/api/tarefas")
def api_criar_tarefa(corpo: dict = Body(...)):
    return db.criar_tarefa(
        lead_id=corpo.get("lead_id"),
        titulo=corpo.get("titulo", "Tarefa"),
        descricao=corpo.get("descricao", ""),
        vence_em=corpo.get("vence_em"),
    )


@app.post("/api/tarefas/{tarefa_id}")
def api_concluir_tarefa(tarefa_id: int, corpo: dict = Body(default={})):
    db.concluir_tarefa(tarefa_id, feito=corpo.get("feito", True))
    return {"ok": True}


# ================================ CHATWOOT =================================

@app.get("/api/chatwoot/status")
def api_chatwoot_status():
    return chatwoot.status()


@app.post("/api/chatwoot/sync")
def api_chatwoot_sync(corpo: dict = Body(default={})):
    if not config.chatwoot_configurado():
        raise HTTPException(400, "Chatwoot não configurado. Preencha CHATWOOT_URL, "
                                 "CHATWOOT_ACCOUNT_ID e CHATWOOT_API_KEY no .env.")
    return chatwoot.sincronizar(max_paginas=int(corpo.get("max_paginas", 20)))


# ================================= WORKER ===================================

@app.get("/api/status")
def api_status():
    canal = obter_canal()
    return {
        "config": config.resumo(),
        "canal": canal.status(),
        "worker": worker.estado(),
        "estatisticas": db.estatisticas(),
        "chatwoot_configurado": config.chatwoot_configurado(),
    }


@app.post("/api/worker/iniciar")
def api_worker_iniciar():
    return worker.iniciar()


@app.post("/api/worker/parar")
def api_worker_parar():
    return worker.parar()


@app.post("/api/worker/ciclo")
def api_worker_ciclo(corpo: dict = Body(default={})):
    """Executa um ciclo agora, sem esperar o agendador."""
    return worker.executar_ciclo(forcar=bool(corpo.get("forcar", True)))


@app.post("/api/config")
def api_config(corpo: dict = Body(...)):
    """
    Ajusta parâmetros de disparo em tempo de execução (não persiste no .env).
    Ex.: intervalo personalizado entre envios (10s, 30s, 60s, 120s ou custom).
    """
    if "pausa_entre_envios" in corpo:
        config.PAUSA_ENTRE_ENVIOS = max(0, int(corpo["pausa_entre_envios"]))
    if "lote_maximo" in corpo:
        config.LOTE_MAXIMO = max(1, int(corpo["lote_maximo"]))
    if "lote_pausa_minutos" in corpo:
        config.LOTE_PAUSA_MINUTOS = max(0, int(corpo["lote_pausa_minutos"]))
    if "alerta_dias" in corpo:
        config.ALERTA_DIAS = max(1, int(corpo["alerta_dias"]))
    return config.resumo()


@app.get("/api/config/evolution")
def api_get_evolution():
    """Configuração atual da Evolution (a chave vem mascarada)."""
    from .channels.evolution import _limpar_url
    chave = db.obter_config("evolution_apikey") or config.EVOLUTION_APIKEY
    canal = obter_canal("evolution")
    return {
        "url": _limpar_url(db.obter_config("evolution_url") or config.EVOLUTION_URL),
        "instancia": db.obter_config("evolution_instancia") or config.EVOLUTION_INSTANCIA,
        "apikey_mascarada": ("•••••••• " + chave[-4:]) if chave else "",
        "tem_chave": bool(chave),
        "webhook_url": db.obter_config("webhook_url") or config.WEBHOOK_URL_PUBLICA,
        "status": canal.status(),
    }


@app.post("/api/config/evolution")
def api_set_evolution(corpo: dict = Body(...)):
    """
    Salva a configuração da Evolution (URL, instância, chave, webhook) no banco.
    Nada disso passa pelo GitHub — fica só aqui no servidor.
    """
    dados = {}
    for campo in ("evolution_url", "evolution_instancia", "webhook_url"):
        if corpo.get(campo) is not None:
            dados[campo] = str(corpo[campo]).strip()
    # A chave só é sobrescrita se você digitar uma nova (salvar sem mexer preserva).
    if corpo.get("evolution_apikey"):
        dados["evolution_apikey"] = str(corpo["evolution_apikey"]).strip()

    if dados:
        db.salvar_config(dados)
    config.CANAL = "evolution"
    limpar_cache()          # recria o canal com os novos valores
    worker.resetar_webhook()  # tenta registrar o webhook de novo
    return obter_canal("evolution").status()


@app.post("/api/config/evolution/testar")
def api_testar_evolution():
    """Testa a conexão com a Evolution usando a configuração salva."""
    limpar_cache()
    return obter_canal("evolution").status()


@app.post("/api/config/evolution/webhook")
def api_registrar_webhook_agora():
    """Registra o webhook na Evolution imediatamente (sem esperar o worker)."""
    url = db.obter_config("webhook_url") or config.WEBHOOK_URL_PUBLICA
    if not url:
        raise HTTPException(400, "Defina a URL do webhook primeiro.")
    resultado = obter_canal("evolution").configurar_webhook(url)
    if resultado.get("ok"):
        worker.resetar_webhook()
    return resultado


@app.post("/api/canal")
def api_trocar_canal(corpo: dict = Body(...)):
    """Troca o canal em execução (não persiste — para persistir, edite o .env)."""
    novo = (corpo.get("canal") or "").lower()
    if novo not in ("evolution", "selenium", "simulado"):
        raise HTTPException(400, "Canal deve ser 'evolution', 'selenium' ou 'simulado'")
    limpar_cache()
    config.CANAL = novo
    return obter_canal().status()


@app.post("/api/evolution/webhook")
def api_configurar_webhook(corpo: dict = Body(default={})):
    """Registra na Evolution API a URL pública deste servidor."""
    url = corpo.get("url") or config.WEBHOOK_URL_PUBLICA
    if not url:
        raise HTTPException(400, "Informe a URL pública (CRM_WEBHOOK_URL no .env ou no corpo)")
    canal = obter_canal("evolution")
    return canal.configurar_webhook(url)


@app.post("/api/optout/recarregar")
def api_recarregar_optout():
    return {"padroes": optout.recarregar()}


@app.post("/api/optout/testar")
def api_testar_optout(corpo: dict = Body(...)):
    detectado, padrao = optout.eh_optout(corpo.get("texto", ""))
    return {"optout": detectado, "padrao": padrao}


# ================================= WEBHOOK ==================================

@app.post("/webhook/evolution")
async def webhook_evolution(request: Request, x_crm_token: str = Header(default="")):
    """
    Recebe MESSAGES_UPSERT da Evolution API e aplica as regras do funil.

    Sempre responde 200: se devolvermos erro, a Evolution reenfileira o evento
    e pode acabar reprocessando a mesma resposta várias vezes.
    """
    if config.WEBHOOK_TOKEN and x_crm_token != config.WEBHOOK_TOKEN:
        return JSONResponse({"ok": False, "erro": "token inválido"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return {"ok": True, "acao": "ignorado", "motivo": "payload não é JSON"}

    mensagem = evo.extrair_mensagem(payload)
    if not mensagem:
        return {"ok": True, "acao": "ignorado", "motivo": "evento não é mensagem"}
    if mensagem["de_mim"]:
        return {"ok": True, "acao": "ignorado", "motivo": "mensagem enviada por nós"}
    if mensagem["grupo"]:
        return {"ok": True, "acao": "ignorado", "motivo": "mensagem de grupo/transmissão"}
    if not mensagem["texto"]:
        return {"ok": True, "acao": "ignorado", "motivo": "mensagem sem texto"}

    try:
        resultado = regras.processar_resposta(
            mensagem["telefone"], mensagem["texto"], mensagem["nome"]
        )
    except Exception:
        log.exception("Erro ao processar resposta")
        return {"ok": False, "acao": "erro"}

    return {"ok": True, **{k: v for k, v in resultado.items() if k != "lead"}}


@app.get("/webhook/evolution", include_in_schema=False)
def webhook_teste():
    """Facilita conferir se a URL pública está chegando até aqui."""
    return {"ok": True, "detalhe": "Webhook do VirtualZap CRM está no ar."}
