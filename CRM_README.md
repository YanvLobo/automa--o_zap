# VirtualZap CRM

Funil de prospecção automático no WhatsApp com etiquetas, alerta de leads esfriando,
saída automática por opt-out e roteamento para atendimento humano.

O app desktop original (`VirtualZap.py`) continua igual — as abas **WhatsApp** e
**Email** não mudaram. O CRM entrou como uma aba nova e um projeto próprio em `crm/`.

---

## 1. Instalação

```bash
pip install -r requirements.txt
copy .env.example .env
```

## 2. Rodar

**Pelo app desktop:** abra o `VirtualZap.py`, vá na aba **📊 CRM** e clique em
*Abrir painel do CRM*. O painel abre no navegador.

**Direto pelo terminal:**

```bash
python run_crm.py
```

Painel em <http://127.0.0.1:8765>. A API tem documentação automática em `/api/docs`.

---

## 3. Como o funil funciona

O pipeline agora é **totalmente personalizável** (botão **☰ Etapas**): crie,
renomeie, recolora, reordene (arrastando) e exclua quantas etapas quiser. As 4
etapas abaixo já vêm prontas e são de **sistema** — não podem ser excluídas
porque as regras automáticas se apoiam nelas (pelo *papel*, não pelo nome, então
você pode renomeá-las à vontade):

| Etapa (papel) | Quando o lead entra nela | Status do funil |
|---|---|---|
| **Novo contato** (`novo`) | ao ser importado | ativo |
| **Aguardando resposta** | após o primeiro disparo | ativo |
| **Respondeu — atendimento manual** (`respondeu`) | respondeu algo que não é opt-out | **pausado** |
| **Não perturbe** (`optout`) | pediu para não receber mais | **removido** |

Cada etapa tem um **status ao entrar** (ativo / pausado / removido / concluído):
é assim que etapas como "Cliente" ou "Perdido" tiram o lead do disparo automático.

O worker acorda a cada 60s, pega os leads `ativo`, confere se o intervalo do
próximo passo já venceu e dispara. Assim que o lead responde, o webhook tira ele
do funil — **o robô nunca dispara por cima de um atendimento humano**.

**Destaque vermelho:** um lead fica vermelho no painel quando passa
`CRM_ALERTA_DIAS` (padrão 3) sem responder o último disparo e ainda está no funil.
É cálculo de exibição, não muda nada no banco.

**Sequências:** edite os textos e os intervalos no botão *✎ Sequências*.
O intervalo é a espera **antes** daquele passo (o passo 1 com `0` dispara assim
que o lead entra). Variáveis: `{nome}`, `{primeiro_nome}`, `{telefone}`.

---

## 4. Canais de envio

Definido em `CRM_CANAL` no `.env`:

| Canal | Envia | Detecta resposta | Uso |
|---|---|---|---|
| `simulado` | não (só loga) | não | **comece por aqui** — testa o funil inteiro sem risco |
| `evolution` | sim | **sim** | produção; único com automação completa |
| `selenium` | sim (WhatsApp Web) | não | envia usando o motor da aba WhatsApp |

> No canal `selenium` as regras de opt-out e roteamento **não disparam sozinhas**,
> porque o Selenium só envia. Você move os cards no Kanban na mão.
> O Chrome aceita um processo por perfil: não use a aba WhatsApp e o canal
> `selenium` ao mesmo tempo.

### Ligando a Evolution API

1. Suba a Evolution API na VPS (Docker) e crie uma instância conectada ao número.
2. Preencha no `.env`:

```ini
CRM_CANAL=evolution
EVOLUTION_URL=https://sua-evolution.seudominio.com
EVOLUTION_INSTANCIA=virtualzap
EVOLUTION_APIKEY=sua-api-key
CRM_WEBHOOK_URL=https://seu-dominio.com/webhook/evolution
```

3. O CRM precisa estar acessível pela internet para receber o webhook.
   Em VPS: `python run_crm.py --host 0.0.0.0` atrás de um proxy.
   Para testar da sua máquina: `ngrok http 8765` e use a URL do ngrok.
4. Registre o webhook na Evolution:

```bash
curl -X POST http://127.0.0.1:8765/api/evolution/webhook
```

O CRM tenta o payload da Evolution v2 e cai para o v1 automaticamente, então
funciona nas duas versões sem configuração extra.

Proteção opcional: defina `CRM_WEBHOOK_TOKEN` e a Evolution precisará mandar o
header `X-CRM-Token`.

---

## 5. Detecção de opt-out

`crm/optout.py` traz uma lista de padrões em português ("sair", "não quero mais",
"para de mandar", "descadastrar", "chega", "sem interesse"…) e uma lista de
exceções para evitar falso positivo ("não quero perder", "não entendi").

A regra é **conservadora de propósito**: na dúvida o lead vai para
*Respondeu — atendimento manual* e um humano decide. Falso positivo custa um lead;
falso negativo custa uma denúncia de spam.

Para adicionar padrões seus, crie `optout_extra.txt` na raiz (uma regex por linha)
e chame `POST /api/optout/recarregar`. Teste qualquer frase em
`POST /api/optout/testar` com `{"texto": "..."}`.

Um lead em opt-out **não volta ao funil por acidente**: a rota de reativação
devolve 409 e só aceita com `forcar=true`.

---

## 6. Proteções anti-bloqueio

Configuráveis no `.env`:

- `CRM_JANELA_INICIO` / `CRM_JANELA_FIM` — só dispara em horário comercial (8h–20h)
- `CRM_FIM_DE_SEMANA=false` — não dispara sábado e domingo
- `CRM_LOTE_MAXIMO=30` — tamanho do lote (mensagens antes da pausa automática)
- `CRM_LOTE_PAUSA_MINUTOS=10` — pausa automática entre lotes
- `CRM_PAUSA_ENTRE_ENVIOS=8` — 8s entre cada mensagem dentro do lote

O botão *⚡ Disparar agora* ignora a janela de horário e a pausa entre lotes
(uso manual, sob sua decisão).

### Lote com pausa automática

Para uma campanha grande sem parecer robô, o worker trabalha **em lotes**:

> envia `CRM_LOTE_MAXIMO` mensagens → pausa `CRM_LOTE_PAUSA_MINUTOS` minutos →
> retoma do ponto onde parou → repete até acabarem os leads.

A pausa só é acionada quando o lote **enche** (havia mais leads esperando). Se
sobraram poucos (lote parcial), ele envia e não força espera. Dá para ajustar os
dois valores em tempo real na barra do painel (**Lote: N msgs · pausa M min**) —
vale já no próximo ciclo, sem reiniciar. Durante a espera, o painel mostra
"⏸ em pausa entre lotes — retoma às HH:MM". Definir a pausa como `0` desliga o
recurso (volta ao disparo contínuo).

---

## 6b. Etiquetas, automações, tarefas e Chatwoot

**Etiquetas (tags) — botão 🏷:** rótulos livres e coloridos, independentes da
etapa. Um lead pode ter várias. Crie/edite/exclua, associe pelo card (Editar) e
**filtre** na barra superior — por uma tag ou por várias, no modo *QUALQUER* (OU)
ou *TODAS* (E).

**Automações por etapa — botão ✎ Sequências → ⚙ Automações:** cada etapa dispara
ações. Dois gatilhos: **ao entrar** e **após X horas** na etapa. Ações: enviar
mensagem, adicionar/remover etiqueta, mover para outra etapa (encadeia as
automações da etapa de destino, com trava contra loop), criar tarefa, parar a
sequência. As de tempo rodam no ciclo do worker; as de entrada, na hora.

**Tarefas — botão ✔:** criadas por automação ou à mão; marque para concluir.
O contador de tarefas pendentes aparece nas métricas.

**Indicador de sequência:** cada card mostra as bolinhas de progresso
(●●○ = 2 de 3 enviadas), o estado da automação (Executando / Pausada / Finalizada
/ Cancelada) e a data/hora do próximo envio. O histórico completo está no botão
*Histórico* do card.

**Rolagem por etapa:** com mais de 7 leads numa coluna, a altura dela trava e
só aquela coluna rola — a página não se mexe. Até 7, a coluna cresce normal.

**Intervalo personalizado:** na barra de filtros, "Intervalo entre envios" ajusta
a pausa entre cada lead (10s, 30s, 1min, 2min ou valor livre), aplicada em tempo
real ao worker.

## 6c. Integração com o Chatwoot — botão 🔄

Sincroniza contatos, conversas, mensagens e etiquetas do Chatwoot para o CRM, de
forma **incremental e sem duplicar** (mensagens são deduplicadas pelo ID do
Chatwoot; contatos, pelo `chatwoot_contact_id` ou telefone).

1. Preencha no `.env` (a **API Key vem sempre da variável de ambiente**, nunca do
   código):

```ini
CHATWOOT_URL=https://seu-chatwoot.com
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_API_KEY=seu-access-token
CHATWOOT_SYNC_MINUTOS=0     # 0 = só manual; >0 = sincroniza sozinho nesse intervalo
```

2. No painel, clique **🔄 Chatwoot → Sincronizar agora**, ou chame
   `POST /api/chatwoot/sync`.

Os *labels* do Chatwoot viram tags; quem respondeu por lá passa pelas mesmas
regras (opt-out sai, resposta ativa vira atendimento manual). Há retry com
backoff, tratamento de rate-limit (HTTP 429) e logs em `crm.chatwoot` para
depuração.

## 7. Estrutura

```
VirtualZap.py         app desktop — abas WhatsApp, Email e CRM
enviar_whatsapp.py    versão antiga, mantida como estava
run_crm.py            sobe o painel pelo terminal
crm/
  config.py           lê o .env (inclui Chatwoot)
  db.py               SQLite: pipeline_stages, tags, lead_tags, leads, sequencias,
                      stage_automations, tarefas, mensagens, eventos, sync_state
  optout.py           detector de descadastro
  regras.py           o que fazer quando o lead responde (resolve etapas por papel)
  automacoes.py       motor de automações por etapa (ao entrar / após X horas)
  chatwoot.py         sync incremental com o Chatwoot
  worker.py           loop de disparo + automações por tempo (APScheduler)
  api.py              FastAPI: painel, API, webhook, endpoints de tags/etapas/etc
  channels/           adaptadores: evolution, selenium, simulado
  static/             painel Kanban (HTML/CSS/JS, sem dependência externa)
crm_leads.db          banco (criado/migrado automaticamente no primeiro uso)
```

O banco **migra sozinho**: se você já tinha um `crm_leads.db` da versão anterior,
as tabelas e colunas novas são adicionadas sem perder os leads existentes.

Trocar de canal ou de provedor de WhatsApp mexe só em `crm/channels/` — o funil,
o banco e o painel não sabem qual canal está por baixo.

---

## 8. Próximos passos naturais

- Migrar de SQLite para PostgreSQL (só `crm/db.py` muda)
- Múltiplas sequências por segmento de lead
- Relatório de conversão por passo da sequência
- Empacotar o CRM no `.exe` (o `VirtualZap.spec` precisa incluir `crm/static/`)
