# Colocar o VirtualZap CRM no ar com a Evolution API (VPS)

Guia completo para o funil **100% automático** (envia e recebe). Ao final, você
terá a Evolution API e o CRM rodando juntos numa VPS, com HTTPS e webhook interno.

Arquitetura: tudo roda em Docker na mesma VPS. O CRM fala com a Evolution pela
rede interna e a Evolution chama o webhook do CRM também internamente — nada de
webhook exposto na internet. O Caddy cuida do HTTPS automático.

```
Internet ──► Caddy ──┬─► evolution.seudominio.com  (Evolution API + QR Code)
                     └─► crm.seudominio.com         (painel do CRM, com senha)

Rede interna Docker:  crm ──► evolution ──► webhook ──► crm
```

---

## Pré-requisitos

1. **Uma VPS** com Ubuntu 22.04+ (2 vCPU / 4 GB RAM já servem bem). A Hostinger,
   que você já usa, tem VPS com Docker pré-instalado.
2. **Um domínio** com acesso ao DNS. Vamos usar dois subdomínios.
3. Um **número de WhatsApp** dedicado para o disparo (de preferência não o seu
   pessoal).

---

## Passo 1 — Apontar o DNS

No painel do seu domínio, crie dois registros **A** apontando para o **IP da VPS**:

| Tipo | Nome | Valor |
|---|---|---|
| A | `evolution` | IP da VPS |
| A | `crm` | IP da VPS |

Espere alguns minutos para propagar. Testa com `ping evolution.seudominio.com`.

---

## Passo 2 — Preparar a VPS

Conecte via SSH e instale Docker (se ainda não tiver):

```bash
curl -fsSL https://get.docker.com | sh
```

Envie o projeto para a VPS (por `git`, `scp` ou o gerenciador de arquivos da
Hostinger). O que importa é ter a pasta do projeto lá, com a subpasta `deploy/`.

---

## Passo 3 — Configurar os segredos

Na VPS, dentro da pasta `deploy/`:

```bash
cd deploy
cp .env.deploy.example .env
nano .env
```

Preencha:
- `EVOLUTION_DOMINIO` e `CRM_DOMINIO` — os subdomínios do passo 1.
- `POSTGRES_PASSWORD` — invente uma senha forte.
- `EVOLUTION_APIKEY` — invente uma chave longa e aleatória (guarde-a).
- `EVOLUTION_INSTANCIA` — ex.: `virtualzap`.
- `CRM_WEBHOOK_TOKEN` — invente um token.

Gere o hash da senha do painel do CRM:

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'SUA_SENHA_AQUI'
```

Copie o resultado para `CRM_SENHA_HASH` no `.env` e escolha o `CRM_USUARIO`.

---

## Passo 4 — Subir tudo

Ainda em `deploy/`:

```bash
docker compose up -d --build
```

Isso sobe Postgres, Redis, Evolution, o CRM e o Caddy. O HTTPS é emitido sozinho
no primeiro acesso. Acompanhe os logs se quiser:

```bash
docker compose logs -f evolution crm
```

---

## Passo 5 — Criar a instância e conectar o WhatsApp

1. Abra `https://evolution.seudominio.com/manager` no navegador.
2. Faça login com a `EVOLUTION_APIKEY` que você definiu.
3. Crie uma instância com **exatamente o mesmo nome** que pôs em
   `EVOLUTION_INSTANCIA` (ex.: `virtualzap`).
4. Clique em conectar e **escaneie o QR Code** com o WhatsApp do número de
   disparo (Aparelhos conectados → Conectar aparelho).
5. O estado deve ficar **open / connected**.

---

## Passo 6 — Ligar o webhook

Com a instância conectada, registre o webhook do CRM (uma vez só). Pela VPS:

```bash
docker compose exec crm python -c "import httpx; print(httpx.post('http://localhost:8765/api/evolution/webhook').json())"
```

Deve responder `{"ok": true, ...}`. Isso diz à Evolution para avisar o CRM sempre
que chegar mensagem — é o que faz o opt-out e o roteamento automático funcionarem.

---

## Passo 7 — Testar de ponta a ponta

1. Abra `https://crm.seudominio.com` (usuário/senha do passo 3).
2. Confira no topo: o chip **canal: evolution ✓** deve estar verde.
3. Adicione **o seu próprio número** como lead, numa sequência de teste com o
   primeiro passo em `0` horas.
4. Clique em **⚡ Disparar agora**. Você deve receber a mensagem no WhatsApp.
5. Responda **"quero saber mais"** → o lead deve ir sozinho para *Respondeu —
   atendimento manual* e sair do funil.
6. Responda **"sair"** com outro lead → deve ir para *Não perturbe (opt-out)*.

Deu tudo isso? O funil automático está no ar. 🎉

---

## Operação do dia a dia

- **Ligar/desligar o funil:** botão no topo do painel (ou `CRM_WORKER_AUTOSTART=true`
  já sobe ligado).
- **Ritmo de envio:** ajuste "Intervalo entre envios" e "Lote / pausa" na barra do
  painel — vale na hora.
- **Ver logs:** `docker compose logs -f crm evolution`.
- **Atualizar o código:** `git pull` (ou reenvie os arquivos) e
  `docker compose up -d --build crm`.
- **Backup:** o que importa é o volume `crm_data` (banco de leads) e
  `evolution_instances` (sessão do WhatsApp). `docker compose down` **não** apaga
  volumes; `docker compose down -v` apaga — cuidado.

---

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Chip `canal: evolution ⚠` vermelho | instância não conectada | refazer o QR no manager (passo 5) |
| Mensagem não sai | número sem WhatsApp ou instância caiu | ver `docker compose logs evolution` |
| Respostas não movem o lead | webhook não registrado | repetir o passo 6 |
| HTTPS não sobe | DNS não propagou / porta 80 fechada | conferir DNS e firewall (abrir 80 e 443) |
| "Chatwoot não configurado" | esperado se não preencheu | opcional; ver CRM_README.md |

---

## E o app desktop (VirtualZap.py)?

Continua para uso local no seu Windows (abas WhatsApp e Email). O CRM na VPS é
independente. Se quiser, pode até tirar a aba CRM do desktop e usar só o painel
web — mas não precisa; os dois convivem.
