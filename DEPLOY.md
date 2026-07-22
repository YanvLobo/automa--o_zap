# Deploy: GitHub → VPS Hostinger (Docker)

Guia passo a passo para publicar o VirtualZap CRM na sua VPS da Hostinger a partir
de um repositório no GitHub, rodando tudo em contêiner.

Fluxo: você sobe o código para o **GitHub** → a VPS **clona** esse repositório →
sobe a pilha com **Docker Compose** → atualizações futuras são um `git pull`.

> Este guia cobre o processo GitHub → VPS. Os detalhes de **conectar o WhatsApp
> (QR Code)** e **registrar o webhook** estão no [SETUP_EVOLUTION.md](SETUP_EVOLUTION.md)
> — são os passos 5 a 7 de lá, reaproveitados aqui na Parte 4.

---

## O que já está pronto no projeto

- `.gitignore` — protege segredos (`.env`, `deploy/.env`), o perfil do Chrome
  (211 MB), os bancos `.db` e os telefones antigos. Nada disso vai para o GitHub.
- `deploy/` — `Dockerfile`, `docker-compose.yml`, `Caddyfile` e o modelo de
  variáveis. É o que a VPS usa para subir tudo.

---

# PARTE 1 — Subir o código para o GitHub

Feito **uma vez** (a inicialização do git e o primeiro commit eu já deixei prontos
na sua máquina).

### 1.1. Criar o repositório no GitHub

1. Acesse <https://github.com/new>.
2. **Repository name:** `virtualzap` (ou o nome que preferir).
3. **Visibilidade:** escolha **Private** (recomendado — o código tem lógica do seu
   negócio; nada de segredo vai junto, mas privado é mais seguro).
4. **NÃO** marque "Add a README / .gitignore / license" (o projeto já tem os seus).
5. Clique em **Create repository**.

### 1.2. Conectar sua pasta ao repositório e enviar

No terminal, dentro da pasta do projeto (`c:\Users\fokal\Desktop\automação_zap`):

```bash
git remote add origin https://github.com/SEU_USUARIO/virtualzap.git
git push -u origin main
```

Na primeira vez o Git vai pedir login do GitHub. Se pedir senha, use um
**Personal Access Token** (o GitHub não aceita mais a senha da conta):
- Gere em <https://github.com/settings/tokens> → *Generate new token (classic)* →
  marque o escopo **repo** → copie e use no lugar da senha.

Pronto — o código está no GitHub. Confira atualizando a página do repositório.

---

# PARTE 2 — Preparar a VPS

### 2.1. Acessar a VPS por SSH

No painel da Hostinger (hPanel → VPS) você encontra o **IP** e as credenciais.
No seu Windows, abra o PowerShell e conecte:

```bash
ssh root@SEU_IP_DA_VPS
```

### 2.2. Garantir o Docker

A Hostinger oferece um template de VPS com **Docker já instalado** (na hora de
criar/reinstalar a VPS, escolha "Ubuntu com Docker"). Para conferir:

```bash
docker --version
docker compose version
```

Se não vier instalado:

```bash
curl -fsSL https://get.docker.com | sh
```

### 2.3. Apontar os subdomínios (DNS)

Para o HTTPS automático funcionar, crie dois registros **A** no DNS do seu
domínio, apontando para o **IP da VPS**:

| Tipo | Nome | Valor |
|---|---|---|
| A | `evolution` | IP da VPS |
| A | `crm` | IP da VPS |

> Sem domínio ainda? Dá para subir e testar pelo IP, mas o Caddy não emite HTTPS
> sem domínio. O ideal é ter os subdomínios antes de seguir.

---

# PARTE 3 — Clonar e subir na VPS

### 3.1. Clonar o repositório

Como o repositório é privado, o `git clone` vai pedir autenticação. Use o mesmo
Personal Access Token da Parte 1 (colando no lugar da senha):

```bash
cd /opt
git clone https://github.com/SEU_USUARIO/virtualzap.git
cd virtualzap
```

### 3.2. Preencher os segredos

```bash
cd deploy
cp .env.deploy.example .env
nano .env
```

Preencha (detalhes de cada campo estão comentados no arquivo):
- `EVOLUTION_DOMINIO`, `CRM_DOMINIO` — os subdomínios do passo 2.3.
- `POSTGRES_PASSWORD` — senha forte inventada.
- `EVOLUTION_APIKEY` — chave longa aleatória (guarde-a).
- `EVOLUTION_INSTANCIA` — ex.: `virtualzap`.
- `CRM_WEBHOOK_TOKEN` — token inventado.
- `CRM_USUARIO` e `CRM_SENHA_HASH` — login do painel. Gere o hash com:

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'SUA_SENHA'
```

Salve o `.env` (no nano: `Ctrl+O`, `Enter`, `Ctrl+X`).

### 3.3. Subir a pilha

```bash
docker compose up -d --build
```

Sobe Postgres, Redis, Evolution API, o CRM e o Caddy (com HTTPS automático).
Acompanhe:

```bash
docker compose ps
docker compose logs -f crm evolution
```

---

# PARTE 4 — Conectar o WhatsApp e testar

Siga os **passos 5, 6 e 7** do [SETUP_EVOLUTION.md](SETUP_EVOLUTION.md):

1. Abrir `https://evolution.seudominio.com/manager`, logar com a `EVOLUTION_APIKEY`,
   criar a instância com o mesmo nome de `EVOLUTION_INSTANCIA` e escanear o QR Code.
2. Registrar o webhook:
   ```bash
   docker compose exec crm python -c "import httpx; print(httpx.post('http://localhost:8765/api/evolution/webhook').json())"
   ```
3. Abrir `https://crm.seudominio.com` (usuário/senha do `.env`), conferir o chip
   **canal: evolution ✓** verde, cadastrar seu número e testar o disparo/resposta.

---

# PARTE 5 — Atualizar o sistema depois (o dia a dia)

Sempre que você mexer no código na sua máquina:

**Na sua máquina (Windows):**
```bash
git add -A
git commit -m "descrição da mudança"
git push
```

**Na VPS (SSH):**
```bash
cd /opt/virtualzap
git pull
cd deploy
docker compose up -d --build crm
```

Só o contêiner do CRM é reconstruído; Evolution, banco e sessão do WhatsApp
continuam de pé. É esse o ganho de subir por GitHub: atualizar vira dois comandos.

---

# Comandos úteis na VPS

| Ação | Comando (dentro de `/opt/virtualzap/deploy`) |
|---|---|
| Ver status dos contêineres | `docker compose ps` |
| Ver logs ao vivo | `docker compose logs -f crm` |
| Reiniciar o CRM | `docker compose restart crm` |
| Parar tudo | `docker compose down` |
| Parar e **apagar dados** (cuidado!) | `docker compose down -v` |
| Espaço em disco | `df -h` |

---

# Segurança — o que NUNCA vai para o GitHub

Já garantido pelo `.gitignore`, mas para você ter tranquilidade:

- `.env` e `deploy/.env` — onde ficam as chaves e senhas reais.
- `perfil_whatsapp/` — sua sessão do WhatsApp Web local.
- `*.db` — o banco de leads.
- `PyWhatKit_DB.txt` — telefones de envios antigos.

Os segredos de produção vivem **só no `deploy/.env` da VPS**, digitados
diretamente lá — nunca passam pelo GitHub.

> Se algum dia uma chave for parar no repositório por engano, considere-a
> vazada: gere uma nova (Evolution/Chatwoot) e troque no `deploy/.env`.
