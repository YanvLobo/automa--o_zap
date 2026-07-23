/* Painel do VirtualZap CRM — Kanban dinâmico, tags, sequência e automações. */

let estado = {
  leads: [],
  stages: [],
  tags: [],
  sequencias: [],
  status: null,
  alertaDias: 3,
  filtroTags: new Set(),
  modoTags: "ou",
};

// ------------------------------- utilidades -------------------------------

async function api(rota, opcoes = {}) {
  const resposta = await fetch(rota, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
    body: opcoes.body ? JSON.stringify(opcoes.body) : undefined,
  });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error(dados.detail || `Erro ${resposta.status}`);
  return dados;
}

let timerToast;
function toast(mensagem, erro = false) {
  const el = document.getElementById("toast");
  el.textContent = mensagem;
  el.classList.toggle("erro", erro);
  el.classList.remove("oculto");
  clearTimeout(timerToast);
  timerToast = setTimeout(() => el.classList.add("oculto"), 3800);
}

function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

function dataCurta(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function textoEspera(lead) {
  if (lead.dias_sem_resposta === null || lead.dias_sem_resposta === undefined) return "sem disparo ainda";
  const dias = lead.dias_sem_resposta;
  if (dias < 1) return `${Math.max(1, Math.round(dias * 24))}h sem resposta`;
  return `${Math.floor(dias)}d sem resposta`;
}

const ROTULO_ESTADO = {
  executando: "Executando", pausada: "Pausada", finalizada: "Finalizada",
  cancelada: "Cancelada", parada: "Parada",
};

// -------------------------------- carga -----------------------------------

async function carregar() {
  const busca = document.getElementById("busca").value.trim();
  const params = new URLSearchParams();
  if (busca) params.set("busca", busca);
  if (estado.filtroTags.size) {
    params.set("tags", [...estado.filtroTags].join(","));
    params.set("modo_tags", estado.modoTags);
  }
  const [dadosLeads, status, seqs] = await Promise.all([
    api("/api/leads?" + params.toString()),
    api("/api/status"),
    api("/api/sequencias"),
  ]);
  estado.leads = dadosLeads.leads;
  estado.stages = dadosLeads.stages;
  estado.tags = dadosLeads.tags;
  estado.alertaDias = dadosLeads.alerta_dias;
  estado.status = status;
  estado.sequencias = seqs.sequencias;
  desenharMetricas();
  desenharCabecalho();
  desenharFiltroTags();
  sincronizarSeletorIntervalo();
  desenharKanban();
}

function sincronizarSeletorIntervalo() {
  const cfg = estado.status.config;
  const sel = document.getElementById("intervalo-envio");
  const atual = String(cfg.pausa_entre_envios);
  if ([...sel.options].some((o) => o.value === atual)) sel.value = atual;
  // Só sobrescreve os campos de lote quando não estão em foco (não atrapalha a digitação).
  const tam = document.getElementById("lote-tamanho");
  const pau = document.getElementById("lote-pausa");
  if (document.activeElement !== tam) tam.value = cfg.lote_maximo;
  if (document.activeElement !== pau) pau.value = cfg.lote_pausa_minutos;
}

function desenharCabecalho() {
  const { canal, worker } = estado.status;

  const chipCanal = document.getElementById("chip-canal");
  chipCanal.textContent = `canal: ${canal.nome}${canal.pronto ? " ✓" : " ⚠"}`;
  chipCanal.className = "chip " + (canal.pronto ? "ok" : "ruim");
  chipCanal.title = canal.detalhe + (canal.recebe_respostas ? "" : "\n⚠ Este canal não detecta respostas automaticamente.");

  const chipWorker = document.getElementById("chip-worker");
  chipWorker.textContent = `funil: ${worker.rodando ? "ligado" : "parado"}`;
  chipWorker.className = "chip " + (worker.rodando ? "ok" : "");
  chipWorker.title = worker.dentro_da_janela ? "Dentro da janela de disparo." : worker.motivo_janela;

  const chipCw = document.getElementById("chip-chatwoot");
  const cwOk = estado.status.chatwoot_configurado;
  chipCw.textContent = `chatwoot: ${cwOk ? "ok" : "off"}`;
  chipCw.className = "chip " + (cwOk ? "ok" : "");
  chipCw.title = cwOk ? "Chatwoot configurado — clique em 🔄 Chatwoot para sincronizar."
                      : "Defina CHATWOOT_URL, CHATWOOT_ACCOUNT_ID e CHATWOOT_API_KEY no .env.";

  const botao = document.getElementById("btn-worker");
  botao.textContent = worker.rodando ? "⏸ Parar funil" : "▶ Ligar funil";
  botao.className = "btn " + (worker.rodando ? "btn-linha" : "btn-cheio");

  const ciclo = worker.ultimo_ciclo || {};
  let linha = ciclo.em ? `último ciclo ${dataCurta(ciclo.em)} — ${ciclo.detalhe}` : ciclo.detalhe || "";
  if (worker.em_pausa_lote && worker.pausa_lote_ate) {
    linha = `⏸ em pausa entre lotes — retoma às ${dataCurta(worker.pausa_lote_ate)}`;
  }
  document.getElementById("ultimo-ciclo").textContent = linha;
}

function desenharMetricas() {
  const e = estado.status.estatisticas;
  const cartoes = [
    { n: e.total, r: "Leads" },
    { n: e.no_funil, r: "No funil" },
    { n: e.esfriando, r: `Esfriando (${estado.alertaDias}d+)`, destaque: e.esfriando > 0 },
    { n: e.mensagens_enviadas, r: "Msgs enviadas" },
    { n: e.mensagens_pendentes, r: "Msgs pendentes" },
    { n: e.respostas_recebidas, r: "Respostas" },
    { n: e.tarefas_pendentes, r: "Tarefas" },
  ];
  document.getElementById("metricas").innerHTML = cartoes
    .map((c) => `<div class="metrica ${c.destaque ? "destaque" : ""}">
        <div class="n">${c.n}</div><div class="r">${c.r}</div></div>`)
    .join("");
}

// ----------------------------- filtro por tags ----------------------------

function desenharFiltroTags() {
  const box = document.getElementById("filtro-tags");
  if (!estado.tags.length) { box.innerHTML = ""; return; }
  const modoBtn = `<span class="pilula" id="pilula-modo" title="Alternar E / OU">
      modo: ${estado.modoTags === "e" ? "TODAS" : "QUALQUER"}</span>`;
  const pilulas = estado.tags.map((t) => `
    <span class="pilula ${estado.filtroTags.has(t.id) ? "ativa" : ""}" data-tag="${t.id}">
      <span class="ponto" style="background:${t.cor}"></span>${escapar(t.nome)} (${t.total})
    </span>`).join("");
  const limpar = estado.filtroTags.size ? `<span class="pilula" id="pilula-limpar">✕ limpar</span>` : "";
  box.innerHTML = pilulas + modoBtn + limpar;

  box.querySelectorAll("[data-tag]").forEach((el) => {
    el.onclick = () => {
      const id = Number(el.dataset.tag);
      estado.filtroTags.has(id) ? estado.filtroTags.delete(id) : estado.filtroTags.add(id);
      carregar();
    };
  });
  const modo = document.getElementById("pilula-modo");
  if (modo) modo.onclick = () => { estado.modoTags = estado.modoTags === "e" ? "ou" : "e"; carregar(); };
  const limparEl = document.getElementById("pilula-limpar");
  if (limparEl) limparEl.onclick = () => { estado.filtroTags.clear(); carregar(); };
}

// -------------------------------- kanban ----------------------------------

function desenharKanban() {
  const soAlerta = document.getElementById("so-alerta").checked;
  const kanban = document.getElementById("kanban");
  kanban.style.gridTemplateColumns = `repeat(${estado.stages.length}, minmax(260px, 1fr))`;

  kanban.innerHTML = estado.stages.map((stage) => {
    const leads = estado.leads.filter(
      (l) => l.etiqueta === stage.slug && (!soAlerta || l.alerta_esfriando)
    );
    const cards = leads.length
      ? leads.map(cardLead).join("")
      : `<div class="vazio">nenhum lead aqui</div>`;
    return `
      <div class="coluna" data-etiqueta="${stage.slug}" style="border-top:2px solid ${stage.cor}">
        <div class="coluna-topo">
          <span class="coluna-titulo" style="color:${stage.cor}">${escapar(stage.nome)}</span>
          <span class="coluna-contador">${leads.length}</span>
        </div>
        <div class="coluna-corpo">${cards}</div>
      </div>`;
  }).join("");

  ligarArrastar();
  ajustarRolagemColunas();
}

const MAX_LEADS_SEM_ROLAGEM = 7;

// Trava a altura da coluna na altura dos primeiros 7 cards; a partir do 8º,
// só o corpo da coluna rola — a página não se mexe.
function ajustarRolagemColunas() {
  document.querySelectorAll(".coluna-corpo").forEach((corpo) => {
    const cards = corpo.querySelectorAll(".lead");
    if (cards.length > MAX_LEADS_SEM_ROLAGEM) {
      const limite = cards[MAX_LEADS_SEM_ROLAGEM]; // 8º card
      const altura = limite.getBoundingClientRect().top - corpo.getBoundingClientRect().top;
      corpo.style.maxHeight = Math.round(altura) + "px";
      corpo.classList.add("rolavel");
    } else {
      corpo.style.maxHeight = "";
      corpo.classList.remove("rolavel");
    }
  });
}

function progressoHtml(lead) {
  const total = lead.total_passos || 0;
  if (!total) return "";
  let bolinhas = "";
  for (let i = 0; i < total; i++) {
    const cls = i < lead.passos_enviados ? "feita"
      : (i === lead.passos_enviados && lead.automacao_estado === "executando") ? "atual" : "";
    bolinhas += `<span class="bolinha ${cls}"></span>`;
  }
  const est = lead.automacao_estado || "parada";
  return `
    <div class="progresso">
      ${bolinhas}
      <span class="rot">${lead.passos_enviados}/${total}</span>
      <span class="estado-auto estado-${est}">${ROTULO_ESTADO[est] || est}</span>
    </div>`;
}

function cardLead(lead) {
  const tags = [];
  if (lead.alerta_esfriando) tags.push(`<span class="tag vermelha">🔥 ${textoEspera(lead)}</span>`);
  else tags.push(`<span class="tag">${textoEspera(lead)}</span>`);

  const tagsLead = (lead.tags || []).map((t) =>
    `<span class="pilula mini"><span class="ponto" style="background:${t.cor}"></span>${escapar(t.nome)}</span>`).join("");

  const proxima = (lead.automacao_estado === "executando" && lead.proxima_execucao)
    ? `<div class="proxima">⏳ próxima: ${dataCurta(lead.proxima_execucao)}</div>` : "";

  return `
    <div class="lead ${lead.alerta_esfriando ? "esfriando" : ""}" draggable="true" data-id="${lead.id}">
      <div class="lead-nome">${escapar(lead.nome || "(sem nome)")}</div>
      <div class="lead-tel">+${escapar(lead.telefone)}</div>
      <div class="lead-meta">${tags.join("")}</div>
      ${progressoHtml(lead)}
      ${proxima}
      ${tagsLead ? `<div class="lead-tags">${tagsLead}</div>` : ""}
      <div class="lead-acoes">
        <button class="btn btn-pequeno" data-acao="historico" data-id="${lead.id}">Histórico</button>
        <button class="btn btn-pequeno" data-acao="editar" data-id="${lead.id}">Editar</button>
        ${lead.status_funil !== "ativo"
          ? `<button class="btn btn-pequeno" data-acao="reativar" data-id="${lead.id}">Reativar</button>` : ""}
      </div>
    </div>`;
}

function ligarArrastar() {
  let arrastando = null;
  document.querySelectorAll(".lead").forEach((card) => {
    card.addEventListener("dragstart", () => { arrastando = card; card.classList.add("arrastando"); });
    card.addEventListener("dragend", () => { card.classList.remove("arrastando"); arrastando = null; });
  });
  document.querySelectorAll(".coluna").forEach((coluna) => {
    coluna.addEventListener("dragover", (e) => { e.preventDefault(); coluna.classList.add("alvo"); });
    coluna.addEventListener("dragleave", () => coluna.classList.remove("alvo"));
    coluna.addEventListener("drop", async (e) => {
      e.preventDefault();
      coluna.classList.remove("alvo");
      if (!arrastando) return;
      try {
        await api(`/api/leads/${arrastando.dataset.id}/etiqueta`, {
          method: "POST", body: { etiqueta: coluna.dataset.etiqueta },
        });
        toast("Lead movido de etapa.");
        await carregar();
      } catch (erro) { toast(erro.message, true); }
    });
  });
}

// -------------------------------- modais ----------------------------------

function abrirModal(html) {
  document.getElementById("modal-conteudo").innerHTML = html;
  document.getElementById("modal").classList.remove("oculto");
}
function fecharModal() { document.getElementById("modal").classList.add("oculto"); }

function opcoesSequencia(selecionada) {
  return estado.sequencias.map((s) =>
    `<option value="${s.id}" ${s.id === selecionada ? "selected" : ""}>${escapar(s.nome)} (${s.passos.length} passos)</option>`
  ).join("");
}
function opcoesStage(selecionada) {
  return estado.stages.map((s) =>
    `<option value="${s.slug}" ${s.slug === selecionada ? "selected" : ""}>${escapar(s.nome)}</option>`
  ).join("");
}

// ---- adicionar leads ----
function modalAdicionar() {
  abrirModal(`
    <h2>Adicionar <span class="marca-cor">leads</span></h2>
    <p class="sub">Um por linha. Aceita <code>Nome|5571999999999</code>, <code>Nome,telefone</code> ou só o número.</p>
    <label class="rotulo">Lista</label>
    <textarea id="in-leads" class="campo" placeholder="Maria Silva|5571999998888&#10;João Souza|71988887777"></textarea>
    <label class="rotulo">Sequência do funil</label>
    <select id="in-seq" class="campo">${opcoesSequencia(estado.sequencias[0]?.id)}</select>
    <div class="linha-botoes">
      <button class="btn btn-cheio" id="btn-salvar-leads">Adicionar ao funil</button>
      <button class="btn" data-fechar>Cancelar</button>
    </div>`);
  document.getElementById("btn-salvar-leads").onclick = async () => {
    const texto = document.getElementById("in-leads").value;
    const sequencia_id = parseInt(document.getElementById("in-seq").value, 10) || null;
    if (!texto.trim()) return toast("Cole ao menos um número.", true);
    try {
      const r = await api("/api/leads", { method: "POST", body: { texto, sequencia_id } });
      toast(`${r.criados} adicionados · ${r.duplicados} já existiam · ${r.invalidos.length} inválidos.`);
      fecharModal(); await carregar();
    } catch (erro) { toast(erro.message, true); }
  };
}

// ---- histórico ----
async function modalHistorico(id) {
  const lead = estado.leads.find((l) => l.id === Number(id));
  const dados = await api(`/api/leads/${id}/historico`);
  const msgs = dados.mensagens.length
    ? dados.mensagens.map((m) => `<div class="msg ${m.direcao} ${m.status === "falha" ? "falha" : ""}">
        ${escapar(m.texto)}
        <span class="quando">${m.direcao === "saida" ? "enviada" : "recebida"} · ${dataCurta(m.criado_em)}
        ${m.status === "falha" ? " · ❌ " + escapar(m.erro) : ""}</span></div>`).join("")
    : `<div class="vazio">nenhuma mensagem trocada ainda</div>`;

  const tarefas = (dados.tarefas || []).length
    ? dados.tarefas.map((t) => `<div class="dica ${t.feito ? "tarefa-feita" : ""}">
        ${t.feito ? "✔" : "▢"} ${escapar(t.titulo)} · ${escapar(t.origem)}</div>`).join("")
    : `<div class="vazio">sem tarefas</div>`;

  const eventos = dados.eventos.slice(0, 10).map((e) =>
    `<div class="dica">${dataCurta(e.criado_em)} · ${escapar(e.tipo)} ${escapar(e.detalhe)}</div>`).join("");

  const seqInfo = lead?.total_passos
    ? `<label class="rotulo">Sequência automática</label>${progressoHtml(lead)}
       ${lead.proxima_mensagem ? `<div class="dica">Próxima: “${escapar(lead.proxima_mensagem.slice(0, 90))}”</div>` : ""}
       ${lead.proxima_execucao && lead.automacao_estado === "executando"
          ? `<div class="dica">Agendada para ${dataCurta(lead.proxima_execucao)}</div>` : ""}`
    : "";

  abrirModal(`
    <h2>${escapar(lead?.nome || "Lead")} <span class="marca-cor">+${escapar(lead?.telefone || "")}</span></h2>
    <p class="sub">${escapar(lead?.etiqueta_rotulo || "")} · ${escapar(lead?.status_rotulo || "")}</p>
    ${seqInfo}
    <label class="rotulo">Conversa</label>
    <div class="historico">${msgs}</div>
    <label class="rotulo">Tarefas</label>${tarefas}
    <label class="rotulo">Eventos</label>${eventos || '<div class="vazio">sem eventos</div>'}`);
}

// ---- editar lead (inclui tags) ----
function modalEditar(id) {
  const lead = estado.leads.find((l) => l.id === Number(id));
  if (!lead) return;
  const idsTags = new Set((lead.tags || []).map((t) => t.id));
  const seletorTags = estado.tags.map((t) =>
    `<span class="pilula ${idsTags.has(t.id) ? "ativa" : ""}" data-tagsel="${t.id}">
      <span class="ponto" style="background:${t.cor}"></span>${escapar(t.nome)}</span>`).join("")
    || `<span class="dica">nenhuma etiqueta criada — use o botão 🏷 Etiquetas</span>`;

  abrirModal(`
    <h2>Editar <span class="marca-cor">lead</span></h2>
    <p class="sub">Criado em ${dataCurta(lead.criado_em)}</p>
    <label class="rotulo">Nome</label>
    <input id="ed-nome" class="campo" style="width:100%" value="${escapar(lead.nome)}">
    <label class="rotulo">Telefone</label>
    <input id="ed-tel" class="campo" style="width:100%" value="${escapar(lead.telefone)}">
    <label class="rotulo">Sequência</label>
    <select id="ed-seq" class="campo">${opcoesSequencia(lead.sequencia_id)}</select>
    <label class="rotulo">Etapa</label>
    <select id="ed-etapa-slug" class="campo">${opcoesStage(lead.etiqueta)}</select>
    <label class="rotulo">Status do funil</label>
    <select id="ed-status" class="campo">
      ${["ativo", "pausado", "removido", "concluido"].map((s) =>
        `<option value="${s}" ${s === lead.status_funil ? "selected" : ""}>${s}</option>`).join("")}
    </select>
    <label class="rotulo">Etapa da sequência (mensagens já enviadas)</label>
    <input id="ed-etapa" class="campo" type="number" min="0" value="${lead.etapa_atual}">
    <label class="rotulo">Etiquetas (clique para marcar)</label>
    <div class="filtro-tags" id="ed-tags">${seletorTags}</div>
    <label class="rotulo">Observações</label>
    <textarea id="ed-obs" class="campo" style="min-height:60px">${escapar(lead.observacoes)}</textarea>
    <div class="linha-botoes">
      <button class="btn btn-cheio" id="btn-salvar-lead">Salvar</button>
      <button class="btn btn-linha" id="btn-excluir-lead">Excluir</button>
      <button class="btn" data-fechar>Cancelar</button>
    </div>`);

  document.querySelectorAll("[data-tagsel]").forEach((el) => {
    el.onclick = () => {
      const tid = Number(el.dataset.tagsel);
      idsTags.has(tid) ? idsTags.delete(tid) : idsTags.add(tid);
      el.classList.toggle("ativa");
    };
  });

  document.getElementById("btn-salvar-lead").onclick = async () => {
    try {
      await api(`/api/leads/${id}`, {
        method: "PATCH",
        body: {
          nome: document.getElementById("ed-nome").value,
          telefone: document.getElementById("ed-tel").value,
          sequencia_id: parseInt(document.getElementById("ed-seq").value, 10) || null,
          etiqueta: document.getElementById("ed-etapa-slug").value,
          status_funil: document.getElementById("ed-status").value,
          etapa_atual: parseInt(document.getElementById("ed-etapa").value, 10) || 0,
          observacoes: document.getElementById("ed-obs").value,
        },
      });
      await api(`/api/leads/${id}/tags`, { method: "POST", body: { tag_ids: [...idsTags] } });
      toast("Lead atualizado."); fecharModal(); await carregar();
    } catch (erro) { toast(erro.message, true); }
  };
  document.getElementById("btn-excluir-lead").onclick = async () => {
    if (!confirm("Excluir este lead e todo o histórico dele?")) return;
    await api(`/api/leads/${id}`, { method: "DELETE" });
    toast("Lead excluído."); fecharModal(); await carregar();
  };
}

async function reativar(id) {
  const lead = estado.leads.find((l) => l.id === Number(id));
  const reiniciar = confirm("Reiniciar a sequência do zero?\n\nOK = do primeiro passo · Cancelar = continuar de onde parou");
  try {
    await api(`/api/leads/${id}/reativar`, { method: "POST", body: { reiniciar } });
    toast("Lead devolvido ao funil."); await carregar();
  } catch (erro) {
    if (lead?.etiqueta === "optout") toast("Lead pediu opt-out — reative só com autorização dele.", true);
    else toast(erro.message, true);
  }
}

// ---- gestão de etapas (pipeline) ----
async function modalEtapas() {
  const linhas = estado.stages.map((s) => `
    <div class="item-lista" draggable="true" data-stage="${s.id}">
      <span class="grip">⠿</span>
      <input type="color" class="cor-input" value="${s.cor}" data-cor="${s.id}">
      <input class="mini cresce" value="${escapar(s.nome)}" data-nome="${s.id}">
      <select class="mini" data-status="${s.id}">
        ${["ativo","pausado","removido","concluido"].map((st) =>
          `<option value="${st}" ${st === s.status_padrao ? "selected" : ""}>${st}</option>`).join("")}
      </select>
      ${s.sistema ? `<span class="badge-sistema">sistema</span>`
                  : `<button class="btn btn-pequeno" data-del-stage="${s.id}">✕</button>`}
    </div>`).join("");

  abrirModal(`
    <h2>Etapas do <span class="marca-cor">pipeline</span></h2>
    <p class="sub">Arraste para reordenar. As colunas do Kanban seguem esta ordem.
       As de <b>sistema</b> são usadas pelas regras de opt-out/resposta e não podem ser excluídas.
       "Status ao entrar" define o que acontece com o funil quando o lead cai na etapa.</p>
    <div id="lista-stages">${linhas}</div>
    <label class="rotulo">Nova etapa</label>
    <div class="item-lista">
      <input type="color" class="cor-input" id="nova-stage-cor" value="#5aa9ff">
      <input class="mini cresce" id="nova-stage-nome" placeholder="Ex.: Reunião marcada">
      <select class="mini" id="nova-stage-status">
        <option value="ativo">ativo</option><option value="pausado">pausado</option>
        <option value="removido">removido</option><option value="concluido">concluido</option>
      </select>
      <button class="btn btn-cheio btn-pequeno" id="btn-nova-stage">+ criar</button>
    </div>
    <div class="linha-botoes"><button class="btn btn-cheio" id="btn-salvar-stages">Salvar alterações</button>
      <button class="btn" data-fechar>Fechar</button></div>`);

  // reordenar por drag
  let arr = null;
  const lista = document.getElementById("lista-stages");
  lista.querySelectorAll("[data-stage]").forEach((el) => {
    el.addEventListener("dragstart", () => { arr = el; el.classList.add("arrastando"); });
    el.addEventListener("dragend", () => { arr = null; el.classList.remove("arrastando"); });
    el.addEventListener("dragover", (e) => {
      e.preventDefault();
      const depois = e.clientY > el.getBoundingClientRect().top + el.offsetHeight / 2;
      if (arr && arr !== el) lista.insertBefore(arr, depois ? el.nextSibling : el);
    });
  });

  lista.querySelectorAll("[data-del-stage]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Excluir esta etapa? Os leads dela vão para a primeira etapa.")) return;
      try { await api(`/api/stages/${btn.dataset.delStage}`, { method: "DELETE" });
        toast("Etapa excluída."); await carregar(); modalEtapas();
      } catch (e) { toast(e.message, true); }
    };
  });

  document.getElementById("btn-nova-stage").onclick = async () => {
    const nome = document.getElementById("nova-stage-nome").value.trim();
    if (!nome) return toast("Dê um nome à etapa.", true);
    await api("/api/stages", { method: "POST", body: {
      nome, cor: document.getElementById("nova-stage-cor").value,
      status_padrao: document.getElementById("nova-stage-status").value } });
    toast("Etapa criada."); await carregar(); modalEtapas();
  };

  document.getElementById("btn-salvar-stages").onclick = async () => {
    try {
      for (const s of estado.stages) {
        await api("/api/stages", { method: "POST", body: {
          id: s.id,
          nome: document.querySelector(`[data-nome="${s.id}"]`).value,
          cor: document.querySelector(`[data-cor="${s.id}"]`).value,
          status_padrao: document.querySelector(`[data-status="${s.id}"]`).value } });
      }
      const ordem = [...lista.querySelectorAll("[data-stage]")].map((el) => Number(el.dataset.stage));
      await api("/api/stages/reordenar", { method: "POST", body: { ids: ordem } });
      toast("Etapas salvas."); fecharModal(); await carregar();
    } catch (e) { toast(e.message, true); }
  };
}

// ---- gestão de tags ----
async function modalTags() {
  const { tags } = await api("/api/tags");
  const linhas = tags.map((t) => `
    <div class="item-lista" data-tag="${t.id}">
      <input type="color" class="cor-input" value="${t.cor}" data-tcor="${t.id}">
      <input class="mini cresce" value="${escapar(t.nome)}" data-tnome="${t.id}">
      <span class="dica">${t.total} lead(s)</span>
      <button class="btn btn-pequeno" data-tsave="${t.id}">salvar</button>
      <button class="btn btn-pequeno" data-tdel="${t.id}">✕</button>
    </div>`).join("") || `<div class="vazio">nenhuma etiqueta ainda</div>`;

  abrirModal(`
    <h2>Etiquetas <span class="marca-cor">(tags)</span></h2>
    <p class="sub">Etiquetas são livres e independem da etapa. Um lead pode ter várias.</p>
    <div>${linhas}</div>
    <label class="rotulo">Nova etiqueta</label>
    <div class="item-lista">
      <input type="color" class="cor-input" id="nova-tag-cor" value="#e5252e">
      <input class="mini cresce" id="nova-tag-nome" placeholder="Ex.: Cliente VIP">
      <button class="btn btn-cheio btn-pequeno" id="btn-nova-tag">+ criar</button>
    </div>
    <div class="linha-botoes"><button class="btn" data-fechar>Fechar</button></div>`);

  document.getElementById("btn-nova-tag").onclick = async () => {
    const nome = document.getElementById("nova-tag-nome").value.trim();
    if (!nome) return toast("Dê um nome à etiqueta.", true);
    await api("/api/tags", { method: "POST", body: { nome, cor: document.getElementById("nova-tag-cor").value } });
    toast("Etiqueta criada."); await carregar(); modalTags();
  };
  document.querySelectorAll("[data-tsave]").forEach((b) => b.onclick = async () => {
    const id = b.dataset.tsave;
    await api("/api/tags", { method: "POST", body: {
      id: Number(id), nome: document.querySelector(`[data-tnome="${id}"]`).value,
      cor: document.querySelector(`[data-tcor="${id}"]`).value } });
    toast("Etiqueta salva."); await carregar(); modalTags();
  });
  document.querySelectorAll("[data-tdel]").forEach((b) => b.onclick = async () => {
    if (!confirm("Excluir esta etiqueta de todos os leads?")) return;
    await api(`/api/tags/${b.dataset.tdel}`, { method: "DELETE" });
    toast("Etiqueta excluída."); await carregar(); modalTags();
  });
}

// ---- tarefas ----
async function modalTarefas() {
  const { tarefas } = await api("/api/tarefas");
  const linhas = tarefas.length ? tarefas.map((t) => `
    <div class="item-lista">
      <input type="checkbox" ${t.feito ? "checked" : ""} data-tarefa="${t.id}">
      <span class="cresce ${t.feito ? "tarefa-feita" : ""}">${escapar(t.titulo)}
        <span class="dica">${t.lead_nome ? "· " + escapar(t.lead_nome) : ""} · ${escapar(t.origem)}</span></span>
    </div>`).join("") : `<div class="vazio">nenhuma tarefa</div>`;
  abrirModal(`
    <h2>Tarefas <span class="marca-cor">do CRM</span></h2>
    <p class="sub">Geradas por automações ou criadas à mão. Marque para concluir.</p>
    <div>${linhas}</div>
    <div class="linha-botoes"><button class="btn" data-fechar>Fechar</button></div>`);
  document.querySelectorAll("[data-tarefa]").forEach((c) => c.onchange = async () => {
    await api(`/api/tarefas/${c.dataset.tarefa}`, { method: "POST", body: { feito: c.checked } });
    toast("Tarefa atualizada."); await carregar();
  });
}

// ---- Evolution (configuração sem terminal) ----
async function modalEvolution() {
  const cfg = await api("/api/config/evolution");
  const st = cfg.status || {};
  const corStatus = st.pronto ? "var(--ok)" : "var(--alerta)";
  abrirModal(`
    <h2>Configurar <span class="marca-cor">Evolution</span></h2>
    <p class="sub">Preencha os dados da sua Evolution. Fica salvo aqui no servidor —
       não vai para o GitHub. Cole o endereço com <code>https://</code> (pode colar
       com <code>/manager</code> no fim que eu limpo).</p>
    <div class="dica" style="color:${corStatus};margin-bottom:6px">● ${escapar(st.detalhe || "sem status")}</div>
    <label class="rotulo">Endereço da Evolution</label>
    <input id="ev-url" class="campo" style="width:100%" value="${escapar(cfg.url)}" placeholder="https://evolutionapi.seusite.com">
    <label class="rotulo">Nome da instância (a conectada ao WhatsApp)</label>
    <input id="ev-inst" class="campo" style="width:100%" value="${escapar(cfg.instancia)}" placeholder="WPP-VM">
    <label class="rotulo">Chave (API key) ${cfg.tem_chave ? "— já salva, deixe em branco para manter" : ""}</label>
    <input id="ev-key" class="campo" style="width:100%" value="" placeholder="${cfg.tem_chave ? cfg.apikey_mascarada : "cole a chave da Evolution"}">
    <label class="rotulo">URL do webhook (o endereço público deste CRM)</label>
    <input id="ev-webhook" class="campo" style="width:100%" value="${escapar(cfg.webhook_url)}" placeholder="http://SEU_IP:8765/webhook/evolution">
    <div class="linha-botoes">
      <button class="btn btn-cheio" id="ev-salvar">Salvar</button>
      <button class="btn btn-linha" id="ev-testar">Testar conexão</button>
      <button class="btn btn-linha" id="ev-webhook-btn">Registrar webhook</button>
      <button class="btn" data-fechar>Fechar</button>
    </div>`);

  document.getElementById("ev-salvar").onclick = async () => {
    const corpo = {
      evolution_url: document.getElementById("ev-url").value,
      evolution_instancia: document.getElementById("ev-inst").value,
      webhook_url: document.getElementById("ev-webhook").value,
    };
    const key = document.getElementById("ev-key").value.trim();
    if (key) corpo.evolution_apikey = key;
    try {
      const st2 = await api("/api/config/evolution", { method: "POST", body: corpo });
      toast(st2.pronto ? "Evolution conectada! ✓" : "Salvo. " + (st2.detalhe || ""), !st2.pronto);
      await carregar();
      modalEvolution();
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("ev-testar").onclick = async () => {
    const st2 = await api("/api/config/evolution/testar", { method: "POST" });
    toast(st2.pronto ? "Conexão ok ✓" : "Sem conexão: " + (st2.detalhe || ""), !st2.pronto);
    modalEvolution();
  };
  document.getElementById("ev-webhook-btn").onclick = async () => {
    try {
      const r = await api("/api/config/evolution/webhook", { method: "POST" });
      toast(r.ok ? "Webhook registrado ✓" : "Falhou: " + (r.detalhe || ""), !r.ok);
    } catch (e) { toast(e.message, true); }
  };
}

// ---- Chatwoot (configuração + sincronização, sem terminal) ----
async function modalChatwoot() {
  const cfg = await api("/api/config/chatwoot");
  const st = cfg.status || {};
  const corStatus = st.ok ? "var(--ok)" : "var(--alerta)";
  abrirModal(`
    <h2>Configurar <span class="marca-cor">Chatwoot</span></h2>
    <p class="sub">Preencha os dados do seu Chatwoot. Fica salvo aqui no servidor —
       não vai para o GitHub. A chave (token) você pega no Chatwoot em
       Perfil → Access Token.</p>
    <div class="dica" style="color:${corStatus};margin-bottom:6px">● ${escapar(st.detalhe || "sem status")}</div>
    <label class="rotulo">Endereço do Chatwoot</label>
    <input id="cw-url" class="campo" style="width:100%" value="${escapar(cfg.url)}" placeholder="https://app.chatwoot.com ou seu domínio">
    <label class="rotulo">ID da conta (Account ID)</label>
    <input id="cw-conta" class="campo" style="width:100%" value="${escapar(cfg.account_id)}" placeholder="1">
    <label class="rotulo">Token de acesso ${cfg.tem_chave ? "— já salvo, deixe em branco para manter" : ""}</label>
    <input id="cw-key" class="campo" style="width:100%" value="" placeholder="${cfg.tem_chave ? cfg.apikey_mascarada : "cole o access token"}">
    ${st.ultimo_run ? `<div class="dica" style="margin-top:8px">Última sincronização: ${dataCurta(st.ultimo_run)}</div>` : ""}
    <p class="sub" style="margin-top:12px">A sincronização traz contatos, conversas, mensagens e etiquetas —
       incremental, sem duplicar. Quem respondeu no Chatwoot passa pelas mesmas regras.</p>
    <div class="linha-botoes">
      <button class="btn btn-cheio" id="cw-salvar">Salvar</button>
      <button class="btn btn-linha" id="cw-sync" ${st.ok ? "" : "disabled"}>🔄 Sincronizar agora</button>
      <button class="btn" data-fechar>Fechar</button>
    </div>`);

  document.getElementById("cw-salvar").onclick = async () => {
    const corpo = {
      url: document.getElementById("cw-url").value,
      account_id: document.getElementById("cw-conta").value,
    };
    const key = document.getElementById("cw-key").value.trim();
    if (key) corpo.api_key = key;
    try {
      const st2 = await api("/api/config/chatwoot", { method: "POST", body: corpo });
      toast(st2.ok ? "Chatwoot conectado! ✓" : "Salvo. " + (st2.detalhe || ""), !st2.ok);
      await carregar();
      modalChatwoot();
    } catch (e) { toast(e.message, true); }
  };

  const b = document.getElementById("cw-sync");
  if (b) b.onclick = async () => {
    b.disabled = true; b.textContent = "sincronizando…";
    try {
      const r = await api("/api/chatwoot/sync", { method: "POST", body: {} });
      toast(r.detalhe || "Sincronização concluída."); fecharModal(); await carregar();
    } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "🔄 Sincronizar agora"; }
  };
}

// ---- sequências (+ automações por etapa) ----
let rascunhoPassos = [];

function modalSequencias(sequenciaId) {
  const seq = estado.sequencias.find((s) => s.id === sequenciaId) || estado.sequencias[0];
  rascunhoPassos = seq ? seq.passos.map((p) => ({ ...p })) : [{ texto: "", intervalo_horas: 0 }];

  abrirModal(`
    <h2>Sequência de <span class="marca-cor">mensagens</span></h2>
    <p class="sub">Variáveis: <code>{nome}</code>, <code>{primeiro_nome}</code>, <code>{telefone}</code>.
       O intervalo é a espera <b>antes</b> de enviar aquele passo.</p>
    <label class="rotulo">Sequência</label>
    <select id="sq-lista" class="campo">${opcoesSequencia(seq?.id)}</select>
    <label class="rotulo">Nome</label>
    <input id="sq-nome" class="campo" style="width:100%" value="${escapar(seq?.nome || "Nova sequência")}">
    <label class="rotulo">Passos</label>
    <div id="sq-passos"></div>
    <button class="btn btn-pequeno" id="sq-add">+ Adicionar passo</button>
    <div class="linha-botoes">
      <button class="btn btn-cheio" id="sq-salvar">Salvar sequência</button>
      <button class="btn" id="sq-nova">Criar nova</button>
      <button class="btn btn-linha" id="sq-automacoes">⚙ Automações por etapa</button>
      <button class="btn" data-fechar>Fechar</button>
    </div>`);

  document.getElementById("sq-lista").onchange = (e) => modalSequencias(Number(e.target.value));
  document.getElementById("sq-add").onclick = () => { coletarPassos(); rascunhoPassos.push({ texto: "", intervalo_horas: 48 }); desenharPassos(); };
  document.getElementById("sq-nova").onclick = () => {
    rascunhoPassos = [{ texto: "", intervalo_horas: 0 }];
    document.getElementById("sq-nome").value = "Nova sequência";
    document.getElementById("sq-lista").value = ""; desenharPassos();
  };
  document.getElementById("sq-automacoes").onclick = modalAutomacoes;
  document.getElementById("sq-salvar").onclick = async () => {
    coletarPassos();
    const idSel = parseInt(document.getElementById("sq-lista").value, 10);
    try {
      await api("/api/sequencias", { method: "POST", body: {
        id: Number.isNaN(idSel) ? null : idSel,
        nome: document.getElementById("sq-nome").value,
        passos: rascunhoPassos.filter((p) => p.texto.trim()) } });
      toast("Sequência salva."); fecharModal(); await carregar();
    } catch (erro) { toast(erro.message, true); }
  };
  desenharPassos();
}

function desenharPassos() {
  document.getElementById("sq-passos").innerHTML = rascunhoPassos.map((p, i) => `
    <div class="passo">
      <div class="passo-topo">
        <span class="passo-titulo">MENSAGEM ${i + 1}</span>
        <button class="btn btn-pequeno" data-remover-passo="${i}">remover</button>
      </div>
      <textarea class="campo" data-passo-texto="${i}">${escapar(p.texto)}</textarea>
      <div class="intervalo">
        <span>Enviar após</span>
        <input type="number" min="0" step="1" data-passo-horas="${i}" value="${p.intervalo_horas}">
        <span>horas ${i === 0 ? "(0 = dispara ao entrar no funil)" : "da mensagem anterior"}</span>
      </div>
    </div>`).join("");
  document.querySelectorAll("[data-remover-passo]").forEach((btn) => btn.onclick = () => {
    coletarPassos(); rascunhoPassos.splice(Number(btn.dataset.removerPasso), 1); desenharPassos();
  });
}
function coletarPassos() {
  document.querySelectorAll("[data-passo-texto]").forEach((el) => rascunhoPassos[Number(el.dataset.passoTexto)].texto = el.value);
  document.querySelectorAll("[data-passo-horas]").forEach((el) => rascunhoPassos[Number(el.dataset.passoHoras)].intervalo_horas = parseFloat(el.value) || 0);
}

// ---- automações por etapa ----
async function modalAutomacoes() {
  const { automacoes } = await api("/api/automacoes");
  const porEtapa = estado.stages.map((s) => {
    const desta = automacoes.filter((a) => a.stage_slug === s.slug);
    const linhas = desta.map((a) => `
      <div class="item-lista">
        <span class="cresce">${escapar(descreverAutomacao(a))}</span>
        <button class="btn btn-pequeno" data-del-auto="${a.id}">✕</button>
      </div>`).join("");
    return `<label class="rotulo" style="color:${s.cor}">${escapar(s.nome)}</label>
      ${linhas || '<div class="dica">sem automações</div>'}`;
  }).join("");

  abrirModal(`
    <h2>Automações por <span class="marca-cor">etapa</span></h2>
    <p class="sub">Cada etapa dispara ações ao receber um lead ou depois de X horas nela.</p>
    <div style="max-height:230px;overflow-y:auto">${porEtapa}</div>
    <label class="rotulo">Nova automação</label>
    <div class="item-lista" style="flex-wrap:wrap">
      <select class="mini" id="au-stage">${estado.stages.map((s) => `<option value="${s.id}" data-slug="${s.slug}">${escapar(s.nome)}</option>`).join("")}</select>
      <select class="mini" id="au-gatilho">
        <option value="ao_entrar">ao entrar</option>
        <option value="apos_horas">após X horas</option>
      </select>
      <input class="mini" id="au-horas" type="number" min="0" value="24" style="width:70px" title="horas (só p/ 'após X horas')">
      <select class="mini" id="au-acao">
        <option value="enviar_mensagem">enviar mensagem</option>
        <option value="adicionar_tag">adicionar etiqueta</option>
        <option value="remover_tag">remover etiqueta</option>
        <option value="mover_etapa">mover para etapa</option>
        <option value="criar_tarefa">criar tarefa</option>
        <option value="parar_sequencia">parar sequência</option>
      </select>
    </div>
    <div class="item-lista" style="flex-wrap:wrap">
      <input class="mini cresce" id="au-texto" placeholder="Texto da mensagem / título da tarefa (use {nome})">
      <select class="mini" id="au-tag">${estado.tags.map((t) => `<option value="${t.id}">${escapar(t.nome)}</option>`).join("") || "<option value=''>—</option>"}</select>
      <select class="mini" id="au-destino">${opcoesStage()}</select>
      <button class="btn btn-cheio btn-pequeno" id="btn-nova-auto">+ criar</button>
    </div>
    <div class="linha-botoes"><button class="btn" id="au-voltar">← Sequências</button>
      <button class="btn" data-fechar>Fechar</button></div>`);

  document.getElementById("au-voltar").onclick = () => modalSequencias();
  document.querySelectorAll("[data-del-auto]").forEach((b) => b.onclick = async () => {
    await api(`/api/automacoes/${b.dataset.delAuto}`, { method: "DELETE" });
    toast("Automação removida."); modalAutomacoes();
  });
  document.getElementById("btn-nova-auto").onclick = async () => {
    const stageSel = document.getElementById("au-stage");
    try {
      await api("/api/automacoes", { method: "POST", body: {
        stage_id: Number(stageSel.value),
        gatilho: document.getElementById("au-gatilho").value,
        horas: parseFloat(document.getElementById("au-horas").value) || 0,
        acao: document.getElementById("au-acao").value,
        texto: document.getElementById("au-texto").value,
        tag_id: Number(document.getElementById("au-tag").value) || null,
        etapa_destino: document.getElementById("au-destino").value } });
      toast("Automação criada."); modalAutomacoes();
    } catch (e) { toast(e.message, true); }
  };
}

function descreverAutomacao(a) {
  const quando = a.gatilho === "apos_horas" ? `após ${a.horas}h` : "ao entrar";
  const mapa = {
    enviar_mensagem: `enviar: “${(a.texto || "").slice(0, 40)}”`,
    adicionar_tag: `adicionar etiqueta #${a.tag_id}`,
    remover_tag: `remover etiqueta #${a.tag_id}`,
    mover_etapa: `mover para "${a.etapa_destino}"`,
    criar_tarefa: `criar tarefa: “${(a.texto || "").slice(0, 40)}”`,
    parar_sequencia: "parar a sequência",
  };
  return `${quando} → ${mapa[a.acao] || a.acao}`;
}

// -------------------------------- eventos ---------------------------------

document.getElementById("btn-add").onclick = modalAdicionar;
document.getElementById("btn-seq").onclick = () => modalSequencias();
document.getElementById("btn-etapas").onclick = modalEtapas;
document.getElementById("btn-tags").onclick = modalTags;
document.getElementById("btn-tarefas").onclick = modalTarefas;
document.getElementById("btn-evolution").onclick = modalEvolution;
document.getElementById("btn-sync").onclick = modalChatwoot;

document.getElementById("btn-worker").onclick = async () => {
  const rodando = estado.status.worker.rodando;
  await api(`/api/worker/${rodando ? "parar" : "iniciar"}`, { method: "POST" });
  toast(rodando ? "Funil automático parado." : "Funil automático ligado.");
  await carregar();
};

document.getElementById("btn-ciclo").onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = "disparando…";
  try { const r = await api("/api/worker/ciclo", { method: "POST", body: { forcar: true } }); toast(r.detalhe); }
  catch (erro) { toast(erro.message, true); }
  finally { e.target.disabled = false; e.target.textContent = "⚡ Disparar agora"; await carregar(); }
};

document.getElementById("so-alerta").onchange = desenharKanban;

document.getElementById("intervalo-envio").onchange = async (e) => {
  let segundos = e.target.value;
  if (segundos === "__custom") {
    const v = prompt("Intervalo entre cada envio, em segundos:", "45");
    if (v === null) return sincronizarSeletorIntervalo();
    segundos = parseInt(v, 10);
    if (Number.isNaN(segundos) || segundos < 0) return toast("Valor inválido.", true);
  }
  try {
    await api("/api/config", { method: "POST", body: { pausa_entre_envios: Number(segundos) } });
    toast(`Intervalo entre envios: ${segundos}s.`);
    await carregar();
  } catch (erro) { toast(erro.message, true); }
};

async function salvarLote() {
  const tamanho = parseInt(document.getElementById("lote-tamanho").value, 10);
  const pausa = parseInt(document.getElementById("lote-pausa").value, 10);
  if (Number.isNaN(tamanho) || tamanho < 1) return toast("Tamanho do lote inválido.", true);
  if (Number.isNaN(pausa) || pausa < 0) return toast("Pausa inválida.", true);
  try {
    await api("/api/config", { method: "POST", body: { lote_maximo: tamanho, lote_pausa_minutos: pausa } });
    toast(pausa > 0 ? `Lote: ${tamanho} msgs, pausa de ${pausa} min entre lotes.`
                    : `Lote: ${tamanho} msgs, sem pausa entre lotes.`);
    await carregar();
  } catch (erro) { toast(erro.message, true); }
}
document.getElementById("lote-tamanho").onchange = salvarLote;
document.getElementById("lote-pausa").onchange = salvarLote;

let timerResize;
window.addEventListener("resize", () => {
  clearTimeout(timerResize);
  timerResize = setTimeout(ajustarRolagemColunas, 150);
});

let timerBusca;
document.getElementById("busca").oninput = () => { clearTimeout(timerBusca); timerBusca = setTimeout(carregar, 300); };

document.addEventListener("click", (e) => {
  if (e.target.matches("[data-fechar]")) return fecharModal();
  const acao = e.target.dataset?.acao;
  if (!acao) return;
  const id = e.target.dataset.id;
  if (acao === "historico") modalHistorico(id);
  if (acao === "editar") modalEditar(id);
  if (acao === "reativar") reativar(id);
});

document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal") fecharModal(); });
document.addEventListener("keydown", (e) => e.key === "Escape" && fecharModal());

carregar().catch((e) => toast(e.message, true));
setInterval(() => { if (document.getElementById("modal").classList.contains("oculto")) carregar().catch(() => {}); }, 20000);
