"""
Camada de dados do CRM (SQLite).

Todas as datas são gravadas em ISO-8601 UTC ("2026-07-20T13:45:00+00:00"),
convertidas para o fuso local só na exibição do painel.

Modelo:
    pipeline_stages   — etapas do funil (customizáveis, ordenáveis)
    tags / lead_tags  — etiquetas livres (N:N com leads)
    leads             — cada lead aponta para uma etapa (coluna `etiqueta` = slug)
    sequencias/passos — mensagens automáticas em sequência
    stage_automations — automações por etapa (ao entrar / após X horas)
    tarefas           — tarefas geradas por automação ou à mão
    mensagens/eventos — histórico
    sync_state        — controle incremental do Chatwoot
"""

import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

# ============================ ETIQUETAS / STATUS ============================
# Slugs das etapas de sistema (seedadas; a rotina de opt-out/resposta as usa).
ETIQUETA_NOVO       = "novo"
ETIQUETA_AGUARDANDO = "aguardando"
ETIQUETA_RESPONDEU  = "respondeu"
ETIQUETA_OPTOUT     = "optout"

# Rótulos das etapas de sistema (fallback; o painel usa os nomes da tabela).
ETIQUETAS = {
    ETIQUETA_NOVO:       "Novo contato",
    ETIQUETA_AGUARDANDO: "Aguardando resposta",
    ETIQUETA_RESPONDEU:  "Respondeu — atendimento manual",
    ETIQUETA_OPTOUT:     "Não perturbe (opt-out)",
}

STATUS_ATIVO     = "ativo"
STATUS_PAUSADO   = "pausado"
STATUS_REMOVIDO  = "removido"
STATUS_CONCLUIDO = "concluido"

STATUS_FUNIL = {
    STATUS_ATIVO:     "No funil automático",
    STATUS_PAUSADO:   "Pausado (atendimento humano)",
    STATUS_REMOVIDO:  "Fora do funil",
    STATUS_CONCLUIDO: "Sequência concluída",
}

# Etapas seedadas no primeiro uso: (slug, nome, cor, papel, status_padrao).
# `papel` liga a etapa às regras automáticas; '' = etapa comum.
STAGES_PADRAO = [
    (ETIQUETA_NOVO,       "Novo contato",                   "#5aa9ff", "novo",      STATUS_ATIVO),
    (ETIQUETA_AGUARDANDO, "Aguardando resposta",            "#ffb84d", "",          STATUS_ATIVO),
    (ETIQUETA_RESPONDEU,  "Respondeu — atendimento manual", "#4ade80", "respondeu", STATUS_PAUSADO),
    (ETIQUETA_OPTOUT,     "Não perturbe (opt-out)",         "#9a9a9a", "optout",    STATUS_REMOVIDO),
]

_lock = threading.RLock()


# ================================ UTILIDADES ================================

def agora() -> datetime:
    return datetime.now(timezone.utc)


def agora_iso() -> str:
    return agora().isoformat()


def ler_data(valor):
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalizar_telefone(bruto: str) -> str:
    digitos = re.sub(r"\D", "", bruto or "")
    if not digitos:
        return ""
    if digitos.startswith("00"):
        digitos = digitos[2:]
    if len(digitos) <= 11 and not digitos.startswith(config.DDI_PADRAO):
        digitos = config.DDI_PADRAO + digitos
    return digitos


def variantes_telefone(bruto: str) -> list:
    """
    Gera as formas equivalentes de um número para casar o mesmo lead mesmo com
    a variação do 9º dígito dos celulares brasileiros.

    Ex.: 5561983269722 (com 9)  <->  556183269722 (sem 9)
    """
    tel = normalizar_telefone(bruto)
    if not tel:
        return []
    variantes = {tel}
    if tel.startswith("55"):
        resto = tel[2:]                       # DDD + número (sem o DDI 55)
        if len(resto) == 11 and resto[2] == "9":       # DDD(2) + 9 + 8 dígitos
            variantes.add("55" + resto[:2] + resto[3:])          # remove o 9 -> 12
        elif len(resto) == 10:                          # DDD(2) + 8 dígitos (sem 9)
            variantes.add("55" + resto[:2] + "9" + resto[2:])    # insere o 9 -> 13
    return list(variantes)


def _slugificar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    base = re.sub(r"[^a-z0-9]+", "_", sem_acento).strip("_")
    return base or "etapa"


# ================================= CONEXÃO ==================================

def conectar() -> sqlite3.Connection:
    caminho = Path(config.CAMINHO_BANCO)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_stages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    nome          TEXT NOT NULL,
    cor           TEXT NOT NULL DEFAULT '#5aa9ff',
    ordem         INTEGER NOT NULL DEFAULT 0,
    papel         TEXT NOT NULL DEFAULT '',      -- '', 'novo', 'respondeu', 'optout'
    sistema       INTEGER NOT NULL DEFAULT 0,    -- 1 = não pode ser excluída
    status_padrao TEXT NOT NULL DEFAULT 'ativo', -- status do funil ao entrar
    criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL UNIQUE,
    cor       TEXT NOT NULL DEFAULT '#e5252e',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lead_tags (
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lead_id, tag_id)
);

CREATE TABLE IF NOT EXISTS sequencias (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL UNIQUE,
    descricao  TEXT DEFAULT '',
    ativa      INTEGER NOT NULL DEFAULT 1,
    criado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sequencia_passos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sequencia_id   INTEGER NOT NULL REFERENCES sequencias(id) ON DELETE CASCADE,
    ordem          INTEGER NOT NULL,
    texto          TEXT NOT NULL,
    intervalo_horas REAL NOT NULL DEFAULT 24,
    UNIQUE (sequencia_id, ordem)
);

CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL DEFAULT '',
    telefone      TEXT NOT NULL UNIQUE,
    etiqueta      TEXT NOT NULL DEFAULT 'novo',   -- slug da etapa atual
    status_funil  TEXT NOT NULL DEFAULT 'ativo',
    sequencia_id  INTEGER REFERENCES sequencias(id) ON DELETE SET NULL,
    etapa_atual   INTEGER NOT NULL DEFAULT 0,
    ultima_mensagem_enviada_em TEXT,
    ultima_resposta_em         TEXT,
    stage_desde   TEXT,
    observacoes   TEXT NOT NULL DEFAULT '',
    chatwoot_contact_id      INTEGER,
    chatwoot_conversation_id INTEGER,
    chatwoot_source_id       TEXT,
    sincronizado_em          TEXT,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mensagens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id      INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    direcao      TEXT NOT NULL,               -- 'saida' | 'entrada'
    texto        TEXT NOT NULL DEFAULT '',
    canal        TEXT NOT NULL DEFAULT '',
    sequencia_id INTEGER,
    passo_ordem  INTEGER,
    status       TEXT NOT NULL DEFAULT 'ok',
    erro         TEXT NOT NULL DEFAULT '',
    chatwoot_msg_id INTEGER UNIQUE,
    criado_em    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id   INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    tipo      TEXT NOT NULL,
    detalhe   TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_automations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id       INTEGER NOT NULL REFERENCES pipeline_stages(id) ON DELETE CASCADE,
    ordem          INTEGER NOT NULL DEFAULT 0,
    gatilho        TEXT NOT NULL DEFAULT 'ao_entrar',  -- 'ao_entrar' | 'apos_horas'
    horas          REAL NOT NULL DEFAULT 0,
    acao           TEXT NOT NULL,   -- enviar_mensagem|adicionar_tag|remover_tag|mover_etapa|criar_tarefa|parar_sequencia
    texto          TEXT NOT NULL DEFAULT '',
    tag_id         INTEGER,
    etapa_destino  TEXT NOT NULL DEFAULT '',
    ativa          INTEGER NOT NULL DEFAULT 1,
    criado_em      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automacao_execucoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id       INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    automation_id INTEGER NOT NULL,
    executado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tarefas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id   INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    titulo    TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    feito     INTEGER NOT NULL DEFAULT 0,
    vence_em  TEXT,
    origem    TEXT NOT NULL DEFAULT 'manual',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    recurso        TEXT PRIMARY KEY,   -- 'chatwoot:contacts', ...
    ultimo_valor   TEXT NOT NULL DEFAULT '',
    atualizado_em  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave         TEXT PRIMARY KEY,   -- 'evolution_url', 'evolution_apikey', ...
    valor         TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_leads_status   ON leads(status_funil);
CREATE INDEX IF NOT EXISTS idx_leads_etiqueta ON leads(etiqueta);
CREATE INDEX IF NOT EXISTS idx_leads_cw       ON leads(chatwoot_contact_id);
CREATE INDEX IF NOT EXISTS idx_msg_lead       ON mensagens(lead_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_eventos_lead   ON eventos(lead_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_ltags_tag      ON lead_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_autoexec       ON automacao_execucoes(lead_id, automation_id);
"""

SEQUENCIA_EXEMPLO = [
    (1, "Olá {nome}! Aqui é da VirtualMark. Vi que sua empresa pode estar "
        "perdendo clientes por falta de presença digital. Posso te mostrar em "
        "2 minutos como resolvemos isso?", 0),
    (2, "Oi {nome}, tudo bem? Passando para confirmar se você chegou a ver "
        "minha mensagem. Consigo te enviar um exemplo do que fizemos para um "
        "cliente do seu segmento.", 48),
    (3, "{nome}, última tentativa por aqui para não te incomodar. Se fizer "
        "sentido conversar, é só responder esta mensagem. Se preferir não "
        "receber mais contatos, responda SAIR que eu removo você da lista.", 72),
]


def _colunas(con, tabela: str) -> set:
    return {c["name"] for c in con.execute(f"PRAGMA table_info({tabela})")}


def _migrar(con) -> None:
    """Adiciona colunas novas a bancos antigos, sem perder dados."""
    if "leads" in {t["name"] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        cols = _colunas(con, "leads")
        adicoes = {
            "stage_desde": "TEXT",
            "chatwoot_contact_id": "INTEGER",
            "chatwoot_conversation_id": "INTEGER",
            "chatwoot_source_id": "TEXT",
            "sincronizado_em": "TEXT",
        }
        for coluna, tipo in adicoes.items():
            if coluna not in cols:
                con.execute(f"ALTER TABLE leads ADD COLUMN {coluna} {tipo}")
        if "chatwoot_msg_id" not in _colunas(con, "mensagens"):
            con.execute("ALTER TABLE mensagens ADD COLUMN chatwoot_msg_id INTEGER")


def _seed_stages(con) -> None:
    existe = con.execute("SELECT COUNT(*) AS n FROM pipeline_stages").fetchone()["n"]
    if existe:
        return
    for i, (slug, nome, cor, papel, status_padrao) in enumerate(STAGES_PADRAO):
        con.execute(
            "INSERT INTO pipeline_stages (slug, nome, cor, ordem, papel, sistema, status_padrao, criado_em) "
            "VALUES (?,?,?,?,?,1,?,?)",
            (slug, nome, cor, i + 1, papel, status_padrao, agora_iso()),
        )


def inicializar() -> None:
    with _lock, conectar() as con:
        _migrar(con)
        con.executescript(SCHEMA)
        _seed_stages(con)
        # stage_desde para leads antigos
        con.execute("UPDATE leads SET stage_desde = criado_em WHERE stage_desde IS NULL")
        if not con.execute("SELECT COUNT(*) AS n FROM sequencias").fetchone()["n"]:
            cur = con.execute(
                "INSERT INTO sequencias (nome, descricao, ativa, criado_em) VALUES (?,?,1,?)",
                ("Prospecção padrão", "Sequência de exemplo — edite os textos no painel.", agora_iso()),
            )
            seq_id = cur.lastrowid
            con.executemany(
                "INSERT INTO sequencia_passos (sequencia_id, ordem, texto, intervalo_horas) VALUES (?,?,?,?)",
                [(seq_id, ordem, texto, horas) for ordem, texto, horas in SEQUENCIA_EXEMPLO],
            )
        con.commit()


# ================================= EVENTOS ==================================

def registrar_evento(con, lead_id, tipo, detalhe="") -> None:
    con.execute(
        "INSERT INTO eventos (lead_id, tipo, detalhe, criado_em) VALUES (?,?,?,?)",
        (lead_id, tipo, detalhe, agora_iso()),
    )


def registrar_mensagem(con, lead_id, direcao, texto, canal="",
                       sequencia_id=None, passo_ordem=None,
                       status="ok", erro="", chatwoot_msg_id=None) -> None:
    con.execute(
        "INSERT INTO mensagens (lead_id, direcao, texto, canal, sequencia_id, "
        "passo_ordem, status, erro, chatwoot_msg_id, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (lead_id, direcao, texto, canal, sequencia_id, passo_ordem, status, erro,
         chatwoot_msg_id, agora_iso()),
    )


# ================================= ETAPAS ==================================

def listar_stages() -> list:
    with _lock, conectar() as con:
        linhas = con.execute("SELECT * FROM pipeline_stages ORDER BY ordem, id").fetchall()
    return [dict(l) for l in linhas]


def mapa_stages() -> dict:
    """{slug: nome} de todas as etapas, na ordem do funil."""
    return {s["slug"]: s["nome"] for s in listar_stages()}


def stage_por_papel(papel: str):
    with _lock, conectar() as con:
        linha = con.execute(
            "SELECT * FROM pipeline_stages WHERE papel = ? ORDER BY ordem LIMIT 1", (papel,)
        ).fetchone()
    return dict(linha) if linha else None


def stage_por_slug(slug: str):
    with _lock, conectar() as con:
        linha = con.execute("SELECT * FROM pipeline_stages WHERE slug = ?", (slug,)).fetchone()
    return dict(linha) if linha else None


def slug_valido(slug: str) -> bool:
    with _lock, conectar() as con:
        return con.execute(
            "SELECT 1 FROM pipeline_stages WHERE slug = ?", (slug,)
        ).fetchone() is not None


def salvar_stage(stage_id, nome, cor="#5aa9ff", status_padrao=STATUS_ATIVO) -> dict:
    ts = agora_iso()
    with _lock, conectar() as con:
        if stage_id:
            con.execute(
                "UPDATE pipeline_stages SET nome = ?, cor = ?, status_padrao = ? WHERE id = ?",
                (nome, cor, status_padrao, stage_id),
            )
        else:
            base = _slugificar(nome)
            slug, n = base, 2
            while con.execute("SELECT 1 FROM pipeline_stages WHERE slug = ?", (slug,)).fetchone():
                slug, n = f"{base}_{n}", n + 1
            ordem = (con.execute("SELECT COALESCE(MAX(ordem),0) AS m FROM pipeline_stages").fetchone()["m"]) + 1
            cur = con.execute(
                "INSERT INTO pipeline_stages (slug, nome, cor, ordem, papel, sistema, status_padrao, criado_em) "
                "VALUES (?,?,?,?,'',0,?,?)",
                (slug, nome, cor, ordem, status_padrao, ts),
            )
            stage_id = cur.lastrowid
        con.commit()
        linha = con.execute("SELECT * FROM pipeline_stages WHERE id = ?", (stage_id,)).fetchone()
    return dict(linha)


def reordenar_stages(ids_em_ordem: list) -> list:
    with _lock, conectar() as con:
        for ordem, sid in enumerate(ids_em_ordem, start=1):
            con.execute("UPDATE pipeline_stages SET ordem = ? WHERE id = ?", (ordem, sid))
        con.commit()
    return listar_stages()


def remover_stage(stage_id: int) -> dict:
    """Exclui uma etapa. Etapas de sistema não podem ser excluídas.
    Os leads da etapa vão para a primeira etapa disponível."""
    with _lock, conectar() as con:
        alvo = con.execute("SELECT * FROM pipeline_stages WHERE id = ?", (stage_id,)).fetchone()
        if not alvo:
            return {"ok": False, "erro": "Etapa não encontrada"}
        if alvo["sistema"]:
            return {"ok": False, "erro": "Etapas de sistema não podem ser excluídas"}
        destino = con.execute(
            "SELECT slug FROM pipeline_stages WHERE id != ? ORDER BY ordem LIMIT 1", (stage_id,)
        ).fetchone()
        destino_slug = destino["slug"] if destino else ETIQUETA_NOVO
        con.execute(
            "UPDATE leads SET etiqueta = ?, stage_desde = ?, atualizado_em = ? WHERE etiqueta = ?",
            (destino_slug, agora_iso(), agora_iso(), alvo["slug"]),
        )
        con.execute("DELETE FROM pipeline_stages WHERE id = ?", (stage_id,))
        con.commit()
    return {"ok": True, "movidos_para": destino_slug}


# ================================== TAGS ===================================

def listar_tags() -> list:
    with _lock, conectar() as con:
        linhas = con.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM lead_tags lt WHERE lt.tag_id = t.id) AS total "
            "FROM tags t ORDER BY t.nome"
        ).fetchall()
    return [dict(l) for l in linhas]


def salvar_tag(tag_id, nome, cor="#e5252e") -> dict:
    ts = agora_iso()
    with _lock, conectar() as con:
        if tag_id:
            con.execute("UPDATE tags SET nome = ?, cor = ? WHERE id = ?", (nome, cor, tag_id))
        else:
            existente = con.execute("SELECT id FROM tags WHERE nome = ?", (nome,)).fetchone()
            if existente:
                tag_id = existente["id"]
                con.execute("UPDATE tags SET cor = ? WHERE id = ?", (cor, tag_id))
            else:
                cur = con.execute(
                    "INSERT INTO tags (nome, cor, criado_em) VALUES (?,?,?)", (nome, cor, ts)
                )
                tag_id = cur.lastrowid
        con.commit()
        linha = con.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return dict(linha)


def remover_tag(tag_id: int) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        con.commit()


def _tags_do_lead(con, lead_id: int) -> list:
    linhas = con.execute(
        "SELECT t.* FROM tags t JOIN lead_tags lt ON lt.tag_id = t.id "
        "WHERE lt.lead_id = ? ORDER BY t.nome", (lead_id,)
    ).fetchall()
    return [dict(l) for l in linhas]


def adicionar_tag_lead(lead_id: int, tag_id: int) -> None:
    with _lock, conectar() as con:
        con.execute(
            "INSERT OR IGNORE INTO lead_tags (lead_id, tag_id) VALUES (?,?)", (lead_id, tag_id)
        )
        registrar_evento(con, lead_id, "tag_adicionada", f"tag {tag_id}")
        con.commit()


def remover_tag_lead(lead_id: int, tag_id: int) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM lead_tags WHERE lead_id = ? AND tag_id = ?", (lead_id, tag_id))
        registrar_evento(con, lead_id, "tag_removida", f"tag {tag_id}")
        con.commit()


def definir_tags_lead(lead_id: int, tag_ids: list) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM lead_tags WHERE lead_id = ?", (lead_id,))
        con.executemany(
            "INSERT OR IGNORE INTO lead_tags (lead_id, tag_id) VALUES (?,?)",
            [(lead_id, t) for t in tag_ids],
        )
        con.commit()


def tag_por_nome(nome: str, cor="#e5252e") -> dict:
    """Devolve a tag (criando se não existir) — usado no sync de labels."""
    return salvar_tag(None, nome, cor)


# ================================== LEADS ===================================

def _proximo_passo_lead(con, lead: dict):
    """Devolve (passo_dict|None, total_passos, proxima_execucao_iso|None)."""
    if not lead.get("sequencia_id"):
        return None, 0, None
    passos = con.execute(
        "SELECT * FROM sequencia_passos WHERE sequencia_id = ? ORDER BY ordem",
        (lead["sequencia_id"],),
    ).fetchall()
    total = len(passos)
    indice = lead["etapa_atual"]
    if indice >= total:
        return None, total, None
    passo = dict(passos[indice])
    base = ler_data(lead.get("ultima_mensagem_enviada_em")) or ler_data(lead.get("criado_em"))
    proxima = (base or agora()) + timedelta(hours=float(passo["intervalo_horas"]))
    return passo, total, proxima.isoformat()


def _linha_para_lead(linha, con=None) -> dict:
    lead = dict(linha)
    enviada = ler_data(lead.get("ultima_mensagem_enviada_em"))
    respondeu = ler_data(lead.get("ultima_resposta_em"))

    dias = None
    if enviada and (not respondeu or respondeu < enviada):
        dias = (agora() - enviada).total_seconds() / 86400

    lead["dias_sem_resposta"] = round(dias, 2) if dias is not None else None
    lead["alerta_esfriando"] = bool(
        dias is not None
        and dias >= config.ALERTA_DIAS
        and lead["status_funil"] in (STATUS_ATIVO, STATUS_CONCLUIDO)
        and lead["etiqueta"] not in (ETIQUETA_RESPONDEU, ETIQUETA_OPTOUT)
    )
    lead["etiqueta_rotulo"] = _MAPA_STAGES_CACHE.get(lead["etiqueta"], lead["etiqueta"])
    lead["status_rotulo"] = STATUS_FUNIL.get(lead["status_funil"], lead["status_funil"])

    fechar = False
    if con is None:
        con = conectar(); fechar = True
    try:
        lead["tags"] = _tags_do_lead(con, lead["id"])
        passo, total, proxima = _proximo_passo_lead(con, lead)
        lead["total_passos"] = total
        lead["passos_enviados"] = min(lead["etapa_atual"], total)
        lead["proxima_mensagem"] = passo["texto"] if passo else None
        lead["proxima_execucao"] = proxima
        lead["pendentes"] = max(total - lead["etapa_atual"], 0)
        # Status da automação para o indicador visual.
        if lead["status_funil"] == STATUS_REMOVIDO:
            estado = "cancelada"
        elif lead["status_funil"] == STATUS_PAUSADO:
            estado = "pausada"
        elif total and lead["etapa_atual"] >= total:
            estado = "finalizada"
        elif lead["status_funil"] == STATUS_ATIVO and lead.get("sequencia_id"):
            estado = "executando"
        else:
            estado = "parada"
        lead["automacao_estado"] = estado
    finally:
        if fechar:
            con.close()
    return lead


# Cache leve dos rótulos de etapa (evita SELECT por lead). Atualizado a cada carga.
_MAPA_STAGES_CACHE = {}


def _atualizar_cache_stages(con) -> None:
    global _MAPA_STAGES_CACHE
    linhas = con.execute("SELECT slug, nome FROM pipeline_stages").fetchall()
    _MAPA_STAGES_CACHE = {l["slug"]: l["nome"] for l in linhas}


def listar_leads(etiqueta=None, status=None, busca=None, tags=None, modo_tags="ou") -> list:
    sql = "SELECT DISTINCT l.* FROM leads l"
    params = []
    if tags:
        sql += " JOIN lead_tags lt ON lt.lead_id = l.id"
    sql += " WHERE 1=1"
    if etiqueta:
        sql += " AND l.etiqueta = ?"; params.append(etiqueta)
    if status:
        sql += " AND l.status_funil = ?"; params.append(status)
    if busca:
        sql += " AND (l.nome LIKE ? OR l.telefone LIKE ?)"; params += [f"%{busca}%", f"%{busca}%"]
    if tags:
        marcadores = ",".join("?" * len(tags))
        sql += f" AND lt.tag_id IN ({marcadores})"; params += list(tags)
    sql += " GROUP BY l.id"
    if tags and modo_tags == "e":
        sql += " HAVING COUNT(DISTINCT lt.tag_id) = ?"; params.append(len(tags))
    sql += " ORDER BY datetime(l.atualizado_em) DESC"
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linhas = con.execute(sql, params).fetchall()
        return [_linha_para_lead(l, con) for l in linhas]


def obter_lead(lead_id: int):
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linha = con.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _linha_para_lead(linha, con) if linha else None


def obter_lead_por_telefone(telefone: str):
    variantes = variantes_telefone(telefone)
    if not variantes:
        return None
    marcadores = ",".join("?" * len(variantes))
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linha = con.execute(
            f"SELECT * FROM leads WHERE telefone IN ({marcadores}) ORDER BY id LIMIT 1",
            variantes,
        ).fetchone()
        return _linha_para_lead(linha, con) if linha else None


def criar_lead(nome, telefone, sequencia_id=None, etiqueta=ETIQUETA_NOVO,
               status=STATUS_ATIVO, observacoes="", chatwoot_contact_id=None) -> dict:
    tel = normalizar_telefone(telefone)
    if not tel:
        raise ValueError("Telefone inválido")
    ts = agora_iso()
    variantes = variantes_telefone(tel)
    marcadores = ",".join("?" * len(variantes))
    with _lock, conectar() as con:
        existente = con.execute(
            f"SELECT * FROM leads WHERE telefone IN ({marcadores}) ORDER BY id LIMIT 1", variantes
        ).fetchone()
        if existente:
            _atualizar_cache_stages(con)
            lead = _linha_para_lead(existente, con)
            lead["ja_existia"] = True
            return lead
        cur = con.execute(
            "INSERT INTO leads (nome, telefone, etiqueta, status_funil, sequencia_id, etapa_atual, "
            "stage_desde, observacoes, chatwoot_contact_id, criado_em, atualizado_em) "
            "VALUES (?,?,?,?,?,0,?,?,?,?,?)",
            (nome.strip(), tel, etiqueta, status, sequencia_id, ts, observacoes,
             chatwoot_contact_id, ts, ts),
        )
        lead_id = cur.lastrowid
        registrar_evento(con, lead_id, "lead_criado", f"{nome} · {tel}")
        con.commit()
        _atualizar_cache_stages(con)
        linha = con.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        lead = _linha_para_lead(linha, con)
    lead["ja_existia"] = False
    # Dispara automações "ao entrar" na etapa inicial.
    _disparar_ao_entrar(lead_id, etiqueta)
    return obter_lead(lead_id)


CAMPOS_EDITAVEIS = {
    "nome", "telefone", "etiqueta", "status_funil",
    "sequencia_id", "etapa_atual", "observacoes",
}


def atualizar_lead(lead_id: int, **campos) -> dict:
    campos = {k: v for k, v in campos.items() if k in CAMPOS_EDITAVEIS and v is not None}
    if "telefone" in campos:
        campos["telefone"] = normalizar_telefone(campos["telefone"])
    mudou_etapa = "etiqueta" in campos
    if not campos:
        return obter_lead(lead_id)
    campos["atualizado_em"] = agora_iso()
    if mudou_etapa:
        campos["stage_desde"] = agora_iso()
    sets = ", ".join(f"{k} = ?" for k in campos)
    with _lock, conectar() as con:
        con.execute(f"UPDATE leads SET {sets} WHERE id = ?", [*campos.values(), lead_id])
        registrar_evento(con, lead_id, "lead_atualizado",
                         ", ".join(f"{k}={v}" for k, v in campos.items()
                                   if k not in ("atualizado_em", "stage_desde")))
        con.commit()
    if mudou_etapa:
        _disparar_ao_entrar(lead_id, campos["etiqueta"])
    return obter_lead(lead_id)


def remover_lead(lead_id: int) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        con.commit()


def mover_etiqueta(lead_id: int, etiqueta: str, status=None, motivo="") -> dict:
    ts = agora_iso()
    campos = {"etiqueta": etiqueta, "stage_desde": ts, "atualizado_em": ts}
    if status:
        campos["status_funil"] = status
    sets = ", ".join(f"{k} = ?" for k in campos)
    with _lock, conectar() as con:
        con.execute(f"UPDATE leads SET {sets} WHERE id = ?", [*campos.values(), lead_id])
        registrar_evento(con, lead_id, "etiqueta_alterada",
                         f"{etiqueta}{' / ' + status if status else ''} {motivo}".strip())
        con.commit()
    _disparar_ao_entrar(lead_id, etiqueta)
    return obter_lead(lead_id)


def historico_lead(lead_id: int) -> dict:
    with _lock, conectar() as con:
        msgs = con.execute(
            "SELECT * FROM mensagens WHERE lead_id = ? ORDER BY datetime(criado_em) ASC", (lead_id,)
        ).fetchall()
        evts = con.execute(
            "SELECT * FROM eventos WHERE lead_id = ? ORDER BY datetime(criado_em) DESC LIMIT 60", (lead_id,)
        ).fetchall()
        tarefas = con.execute(
            "SELECT * FROM tarefas WHERE lead_id = ? ORDER BY feito, datetime(criado_em) DESC", (lead_id,)
        ).fetchall()
    return {
        "mensagens": [dict(m) for m in msgs],
        "eventos": [dict(e) for e in evts],
        "tarefas": [dict(t) for t in tarefas],
    }


def _disparar_ao_entrar(lead_id: int, slug: str) -> None:
    """Executa as automações 'ao_entrar' da etapa (import tardio evita ciclo)."""
    try:
        from . import automacoes
        automacoes.ao_entrar(lead_id, slug)
    except Exception:
        import logging
        logging.getLogger("crm.db").exception("Falha ao disparar automações de entrada")


# =============================== SEQUÊNCIAS =================================

def listar_sequencias() -> list:
    with _lock, conectar() as con:
        seqs = con.execute("SELECT * FROM sequencias ORDER BY id").fetchall()
        resultado = []
        for s in seqs:
            passos = con.execute(
                "SELECT * FROM sequencia_passos WHERE sequencia_id = ? ORDER BY ordem", (s["id"],)
            ).fetchall()
            item = dict(s); item["passos"] = [dict(p) for p in passos]
            resultado.append(item)
    return resultado


def obter_sequencia(sequencia_id: int):
    with _lock, conectar() as con:
        s = con.execute("SELECT * FROM sequencias WHERE id = ?", (sequencia_id,)).fetchone()
        if not s:
            return None
        passos = con.execute(
            "SELECT * FROM sequencia_passos WHERE sequencia_id = ? ORDER BY ordem", (sequencia_id,)
        ).fetchall()
    item = dict(s); item["passos"] = [dict(p) for p in passos]
    return item


def salvar_sequencia(sequencia_id, nome, descricao, passos, ativa=True) -> dict:
    ts = agora_iso()
    with _lock, conectar() as con:
        if sequencia_id:
            con.execute("UPDATE sequencias SET nome = ?, descricao = ?, ativa = ? WHERE id = ?",
                        (nome, descricao, 1 if ativa else 0, sequencia_id))
            con.execute("DELETE FROM sequencia_passos WHERE sequencia_id = ?", (sequencia_id,))
        else:
            cur = con.execute("INSERT INTO sequencias (nome, descricao, ativa, criado_em) VALUES (?,?,?,?)",
                              (nome, descricao, 1 if ativa else 0, ts))
            sequencia_id = cur.lastrowid
        con.executemany(
            "INSERT INTO sequencia_passos (sequencia_id, ordem, texto, intervalo_horas) VALUES (?,?,?,?)",
            [(sequencia_id, i + 1, p.get("texto", ""), float(p.get("intervalo_horas", 24)))
             for i, p in enumerate(passos)],
        )
        con.commit()
    return obter_sequencia(sequencia_id)


def remover_sequencia(sequencia_id: int) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM sequencias WHERE id = ?", (sequencia_id,))
        con.commit()


# =========================== AUTOMAÇÕES POR ETAPA ==========================

def listar_automacoes(stage_id=None) -> list:
    sql = ("SELECT a.*, s.slug AS stage_slug, s.nome AS stage_nome FROM stage_automations a "
           "JOIN pipeline_stages s ON s.id = a.stage_id")
    params = []
    if stage_id:
        sql += " WHERE a.stage_id = ?"; params.append(stage_id)
    sql += " ORDER BY a.stage_id, a.ordem, a.id"
    with _lock, conectar() as con:
        linhas = con.execute(sql, params).fetchall()
    return [dict(l) for l in linhas]


def salvar_automacao(dados: dict) -> dict:
    ts = agora_iso()
    campos = ("stage_id", "gatilho", "horas", "acao", "texto", "tag_id", "etapa_destino", "ativa", "ordem")
    with _lock, conectar() as con:
        if dados.get("id"):
            sets = ", ".join(f"{c} = ?" for c in campos)
            con.execute(f"UPDATE stage_automations SET {sets} WHERE id = ?",
                        [*(dados.get(c) for c in campos), dados["id"]])
            aid = dados["id"]
        else:
            cur = con.execute(
                "INSERT INTO stage_automations (stage_id, gatilho, horas, acao, texto, tag_id, "
                "etapa_destino, ativa, ordem, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (dados.get("stage_id"), dados.get("gatilho", "ao_entrar"), float(dados.get("horas") or 0),
                 dados.get("acao"), dados.get("texto", ""), dados.get("tag_id"),
                 dados.get("etapa_destino", ""), 1 if dados.get("ativa", True) else 0,
                 int(dados.get("ordem") or 0), ts),
            )
            aid = cur.lastrowid
        con.commit()
        linha = con.execute("SELECT * FROM stage_automations WHERE id = ?", (aid,)).fetchone()
    return dict(linha)


def remover_automacao(automation_id: int) -> None:
    with _lock, conectar() as con:
        con.execute("DELETE FROM stage_automations WHERE id = ?", (automation_id,))
        con.commit()


def automacoes_por_slug(slug: str, gatilho: str) -> list:
    with _lock, conectar() as con:
        linhas = con.execute(
            "SELECT a.* FROM stage_automations a JOIN pipeline_stages s ON s.id = a.stage_id "
            "WHERE s.slug = ? AND a.gatilho = ? AND a.ativa = 1 ORDER BY a.ordem, a.id",
            (slug, gatilho),
        ).fetchall()
    return [dict(l) for l in linhas]


def automacao_ja_executada(lead_id: int, automation_id: int, desde_iso: str) -> bool:
    with _lock, conectar() as con:
        return con.execute(
            "SELECT 1 FROM automacao_execucoes WHERE lead_id = ? AND automation_id = ? "
            "AND datetime(executado_em) >= datetime(?)",
            (lead_id, automation_id, desde_iso or "1970-01-01"),
        ).fetchone() is not None


def marcar_automacao_executada(lead_id: int, automation_id: int) -> None:
    with _lock, conectar() as con:
        con.execute(
            "INSERT INTO automacao_execucoes (lead_id, automation_id, executado_em) VALUES (?,?,?)",
            (lead_id, automation_id, agora_iso()),
        )
        con.commit()


def leads_para_automacao_tempo() -> list:
    """Leads ativos/pausados com automações 'apos_horas' pendentes na etapa atual."""
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linhas = con.execute(
            "SELECT * FROM leads WHERE status_funil IN (?,?,?)",
            (STATUS_ATIVO, STATUS_PAUSADO, STATUS_CONCLUIDO),
        ).fetchall()
        return [_linha_para_lead(l, con) for l in linhas]


# ================================ TAREFAS ==================================

def criar_tarefa(lead_id, titulo, descricao="", vence_em=None, origem="manual") -> dict:
    with _lock, conectar() as con:
        cur = con.execute(
            "INSERT INTO tarefas (lead_id, titulo, descricao, vence_em, origem, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (lead_id, titulo, descricao, vence_em, origem, agora_iso()),
        )
        registrar_evento(con, lead_id, "tarefa_criada", titulo)
        con.commit()
        linha = con.execute("SELECT * FROM tarefas WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(linha)


def listar_tarefas(apenas_pendentes=False) -> list:
    sql = ("SELECT t.*, l.nome AS lead_nome, l.telefone AS lead_telefone "
           "FROM tarefas t LEFT JOIN leads l ON l.id = t.lead_id")
    if apenas_pendentes:
        sql += " WHERE t.feito = 0"
    sql += " ORDER BY t.feito, datetime(t.criado_em) DESC"
    with _lock, conectar() as con:
        return [dict(l) for l in con.execute(sql).fetchall()]


def concluir_tarefa(tarefa_id: int, feito=True) -> None:
    with _lock, conectar() as con:
        con.execute("UPDATE tarefas SET feito = ? WHERE id = ?", (1 if feito else 0, tarefa_id))
        con.commit()


# ============================== SYNC STATE =================================

# ============================ CONFIGURAÇÕES ================================
# Guardadas no banco (persistem no volume) e editáveis pelo painel — servem para
# configurar a Evolution sem mexer em .env nem terminal.

def obter_config(chave: str, padrao: str = "") -> str:
    with _lock, conectar() as con:
        linha = con.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha and linha["valor"] != "" else padrao


def obter_configs() -> dict:
    with _lock, conectar() as con:
        linhas = con.execute("SELECT chave, valor FROM configuracoes").fetchall()
    return {l["chave"]: l["valor"] for l in linhas}


def salvar_config(dados: dict) -> None:
    ts = agora_iso()
    with _lock, conectar() as con:
        for chave, valor in dados.items():
            con.execute(
                "INSERT INTO configuracoes (chave, valor, atualizado_em) VALUES (?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, "
                "atualizado_em = excluded.atualizado_em",
                (chave, "" if valor is None else str(valor), ts),
            )
        con.commit()


def obter_sync(recurso: str) -> str:
    with _lock, conectar() as con:
        linha = con.execute("SELECT ultimo_valor FROM sync_state WHERE recurso = ?", (recurso,)).fetchone()
    return linha["ultimo_valor"] if linha else ""


def salvar_sync(recurso: str, valor: str) -> None:
    with _lock, conectar() as con:
        con.execute(
            "INSERT INTO sync_state (recurso, ultimo_valor, atualizado_em) VALUES (?,?,?) "
            "ON CONFLICT(recurso) DO UPDATE SET ultimo_valor = excluded.ultimo_valor, "
            "atualizado_em = excluded.atualizado_em",
            (recurso, valor, agora_iso()),
        )
        con.commit()


def lead_por_chatwoot(contact_id: int):
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linha = con.execute("SELECT * FROM leads WHERE chatwoot_contact_id = ?", (contact_id,)).fetchone()
        return _linha_para_lead(linha, con) if linha else None


def vincular_chatwoot(lead_id, contact_id=None, conversation_id=None, source_id=None) -> None:
    campos, params = [], []
    if contact_id is not None:
        campos.append("chatwoot_contact_id = ?"); params.append(contact_id)
    if conversation_id is not None:
        campos.append("chatwoot_conversation_id = ?"); params.append(conversation_id)
    if source_id is not None:
        campos.append("chatwoot_source_id = ?"); params.append(source_id)
    campos.append("sincronizado_em = ?"); params.append(agora_iso())
    with _lock, conectar() as con:
        con.execute(f"UPDATE leads SET {', '.join(campos)} WHERE id = ?", [*params, lead_id])
        con.commit()


def mensagem_chatwoot_existe(msg_id: int) -> bool:
    with _lock, conectar() as con:
        return con.execute(
            "SELECT 1 FROM mensagens WHERE chatwoot_msg_id = ?", (msg_id,)
        ).fetchone() is not None


def importar_mensagem_chatwoot(lead_id, msg_id, direcao, texto, criado_em=None) -> bool:
    """Grava mensagem vinda do Chatwoot sem duplicar. Retorna True se inseriu."""
    with _lock, conectar() as con:
        if con.execute("SELECT 1 FROM mensagens WHERE chatwoot_msg_id = ?", (msg_id,)).fetchone():
            return False
        con.execute(
            "INSERT INTO mensagens (lead_id, direcao, texto, canal, status, chatwoot_msg_id, criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (lead_id, direcao, texto, "chatwoot", "ok", msg_id, criado_em or agora_iso()),
        )
        con.commit()
    return True


# ========================== CONSULTAS DO WORKER =============================

def leads_prontos_para_disparo(limite: int) -> list:
    agora_dt = agora()
    prontos = []
    with _lock, conectar() as con:
        _atualizar_cache_stages(con)
        linhas = con.execute(
            "SELECT * FROM leads WHERE status_funil = ? AND sequencia_id IS NOT NULL "
            "ORDER BY datetime(COALESCE(ultima_mensagem_enviada_em, criado_em)) ASC",
            (STATUS_ATIVO,),
        ).fetchall()

        cache_passos = {}
        for linha in linhas:
            if len(prontos) >= limite:
                break
            seq_id = linha["sequencia_id"]
            if seq_id not in cache_passos:
                cache_passos[seq_id] = con.execute(
                    "SELECT * FROM sequencia_passos WHERE sequencia_id = ? ORDER BY ordem", (seq_id,)
                ).fetchall()
            passos = cache_passos[seq_id]
            proximo_indice = linha["etapa_atual"]

            if proximo_indice >= len(passos):
                con.execute("UPDATE leads SET status_funil = ?, atualizado_em = ? WHERE id = ?",
                            (STATUS_CONCLUIDO, agora_iso(), linha["id"]))
                registrar_evento(con, linha["id"], "sequencia_concluida", f"{len(passos)} passos enviados")
                continue

            passo = passos[proximo_indice]
            base = ler_data(linha["ultima_mensagem_enviada_em"]) or ler_data(linha["criado_em"])
            vencimento = (base or agora_dt) + timedelta(hours=float(passo["intervalo_horas"]))
            if agora_dt >= vencimento:
                lead = _linha_para_lead(linha, con)
                lead["passo"] = dict(passo)
                prontos.append(lead)
        con.commit()
    return prontos


def marcar_envio(lead_id, sequencia_id, passo_ordem, texto, canal, sucesso, erro="") -> None:
    ts = agora_iso()
    with _lock, conectar() as con:
        registrar_mensagem(con, lead_id, "saida", texto, canal, sequencia_id, passo_ordem,
                           "ok" if sucesso else "falha", erro)
        if sucesso:
            con.execute(
                "UPDATE leads SET etapa_atual = ?, ultima_mensagem_enviada_em = ?, "
                "etiqueta = CASE WHEN etiqueta = ? THEN ? ELSE etiqueta END, "
                "stage_desde = CASE WHEN etiqueta = ? THEN ? ELSE stage_desde END, "
                "atualizado_em = ? WHERE id = ?",
                (passo_ordem, ts, ETIQUETA_NOVO, ETIQUETA_AGUARDANDO,
                 ETIQUETA_NOVO, ts, ts, lead_id),
            )
            registrar_evento(con, lead_id, "mensagem_enviada", f"passo {passo_ordem}")
        else:
            registrar_evento(con, lead_id, "falha_envio", f"passo {passo_ordem}: {erro}")
        con.commit()


def registrar_resposta(lead_id, texto, etiqueta, status, motivo) -> dict:
    ts = agora_iso()
    with _lock, conectar() as con:
        registrar_mensagem(con, lead_id, "entrada", texto, "webhook")
        con.execute(
            "UPDATE leads SET etiqueta = ?, status_funil = ?, ultima_resposta_em = ?, "
            "stage_desde = ?, atualizado_em = ? WHERE id = ?",
            (etiqueta, status, ts, ts, ts, lead_id),
        )
        registrar_evento(con, lead_id, "resposta_recebida", motivo)
        con.commit()
    _disparar_ao_entrar(lead_id, etiqueta)
    return obter_lead(lead_id)


# ============================== ESTATÍSTICAS ================================

def estatisticas() -> dict:
    leads = listar_leads()
    stages = listar_stages()
    por_etiqueta = {s["slug"]: 0 for s in stages}
    for lead in leads:
        por_etiqueta[lead["etiqueta"]] = por_etiqueta.get(lead["etiqueta"], 0) + 1
    with _lock, conectar() as con:
        enviadas = con.execute(
            "SELECT COUNT(*) AS n FROM mensagens WHERE direcao='saida' AND status='ok'"
        ).fetchone()["n"]
        recebidas = con.execute("SELECT COUNT(*) AS n FROM mensagens WHERE direcao='entrada'").fetchone()["n"]
        tarefas_pendentes = con.execute("SELECT COUNT(*) AS n FROM tarefas WHERE feito=0").fetchone()["n"]
    pendentes = sum(l["pendentes"] for l in leads)
    return {
        "total": len(leads),
        "por_etiqueta": por_etiqueta,
        "no_funil": sum(1 for l in leads if l["status_funil"] == STATUS_ATIVO),
        "esfriando": sum(1 for l in leads if l["alerta_esfriando"]),
        "mensagens_enviadas": enviadas,
        "mensagens_pendentes": pendentes,
        "respostas_recebidas": recebidas,
        "tarefas_pendentes": tarefas_pendentes,
    }
