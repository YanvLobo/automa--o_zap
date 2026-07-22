"""
VirtualZap — Disparo automatizado de WhatsApp e Email + CRM de prospecção
Abas: WhatsApp | Email | CRM

Requisitos:
    pip install -r requirements.txt
    (mínimo para WhatsApp/Email: pip install selenium webdriver-manager)

Hostinger SMTP: smtp.hostinger.com, porta 587 (TLS)

Personalização: use {nome} na mensagem para substituir pelo nome do destinatário.
Formato da lista de emails com nome: nome|email@dominio.com
Formato da lista sem nome:          email@dominio.com

A aba CRM sobe o painel web de leads (funil automático, etiquetas, opt-out).
Ela é opcional: se as dependências do CRM não estiverem instaladas, as abas
WhatsApp e Email continuam funcionando normalmente.
"""

import os
import re
import ssl
import time
import smtplib
import threading
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ========================== PALETA ==========================
PRETO          = "#0a0a0a"
CINZA_CARD     = "#161616"
CINZA_BORDA    = "#2a2a2a"
VERMELHO_MARCA = "#e5252e"   # vermelho da marca (VirtualMark)
VERMELHO_HOVER = "#ff3b43"   # hover dos botões
BRANCO         = "#f5f5f5"
CINZA_TEXTO    = "#9a9a9a"
VERMELHO       = "#ff5c5c"   # falhas no log
VERDE_OK       = "#4ade80"   # sucesso no log (mantido só p/ leitura rápida)
CINZA_ABA      = "#111111"


# ===================== LÓGICA WHATSAPP ======================

def wpp_iniciar_navegador(log):
    options = webdriver.ChromeOptions()
    caminho_perfil = os.path.join(os.path.abspath(os.path.dirname(__file__)), "perfil_whatsapp")
    options.add_argument(f"--user-data-dir={caminho_perfil}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--remote-debugging-port=9222")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.get("https://web.whatsapp.com")
    log("Abrindo o WhatsApp Web...")
    log("Se for a primeira vez, escaneie o QR Code com o celular.")
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.XPATH, '//div[@id="side"]'))
    )
    log("✅ WhatsApp Web carregado com sucesso.\n")
    return driver


def wpp_enviar(driver, numero, mensagem, log):
    numero = numero.replace("+", "").replace(" ", "").replace("-", "")
    url = f"https://web.whatsapp.com/send?phone={numero}&text={urllib.parse.quote(mensagem)}"
    driver.get(url)
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((
                By.XPATH,
                '//div[@contenteditable="true"][@data-tab="10"] | //footer//div[@contenteditable="true"]'
            ))
        )
        botao = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((
                By.XPATH,
                '//span[@data-icon="send" or @data-icon="wds-ic-send-filled"]/ancestor::button'
            ))
        )
        time.sleep(1)
        botao.click()
        time.sleep(2)
        log(f"✅ Enviado para {numero}")
        return True
    except Exception:
        log(f"❌ Falha ao enviar para {numero}")
        return False


# ====================== LÓGICA EMAIL ========================

def email_enviar(smtp_host, smtp_port, remetente, senha,
                 destinatario, nome, assunto, corpo, anexos, log):
    try:
        msg = MIMEMultipart()
        msg["From"]    = remetente
        msg["To"]      = destinatario
        msg["Subject"] = assunto.replace("{nome}", nome)

        texto = corpo.replace("{nome}", nome)
        msg.attach(MIMEText(texto, "plain", "utf-8"))

        for caminho in anexos:
            if not caminho:
                continue
            with open(caminho, "rb") as f:
                parte = MIMEBase("application", "octet-stream")
                parte.set_payload(f.read())
            encoders.encode_base64(parte)
            parte.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(caminho)}"
            )
            msg.attach(parte)

        contexto = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=contexto)
            server.login(remetente, senha)
            server.sendmail(remetente, destinatario, msg.as_bytes())

        log(f"✅ Email enviado para {destinatario}")
        return True
    except Exception as e:
        log(f"❌ Falha para {destinatario}: {e}")
        return False


# ======================== INTERFACE =========================

def _label(parent, texto, fg=None, font=None):
    return tk.Label(
        parent, text=texto, bg=PRETO,
        fg=fg or CINZA_TEXTO,
        font=font or ("Segoe UI", 9)
    )

def _card(parent):
    return tk.Frame(parent, bg=CINZA_CARD,
                    highlightbackground=CINZA_BORDA,
                    highlightthickness=1, bd=0)

def _texto(parent, height=5):
    return tk.Text(
        parent, height=height, font=("Segoe UI", 10),
        bg=CINZA_CARD, fg=BRANCO, insertbackground=VERMELHO_MARCA,
        relief="flat", padx=10, pady=8, wrap="word"
    )

def _entry(parent, show=None):
    return tk.Entry(
        parent, font=("Segoe UI", 10),
        bg=CINZA_CARD, fg=BRANCO, insertbackground=VERMELHO_MARCA,
        relief="flat", show=show
    )

def _secao(parent, texto):
    tk.Label(
        parent, text=texto, bg=PRETO, fg=VERMELHO_MARCA,
        font=("Segoe UI", 9, "bold")
    ).pack(anchor="w", pady=(12, 4))

def _botao_principal(parent, texto, cmd):
    btn = tk.Button(
        parent, text=texto,
        bg=VERMELHO_MARCA, fg=BRANCO,
        activebackground=VERMELHO_HOVER, activeforeground=BRANCO,
        font=("Segoe UI", 11, "bold"),
        relief="flat", pady=11, cursor="hand2",
        command=cmd
    )
    btn.pack(fill="x", pady=(14, 0))
    btn.bind("<Enter>", lambda e: btn.config(bg=VERMELHO_HOVER))
    btn.bind("<Leave>", lambda e: btn.config(bg=VERMELHO_MARCA))
    return btn

def _log_widget(parent):
    card = _card(parent)
    card.pack(fill="both", expand=True, pady=(0, 0))
    log_box = scrolledtext.ScrolledText(
        card, font=("Consolas", 9), state="disabled",
        bg=CINZA_CARD, fg="#c8c8c8", relief="flat",
        padx=10, pady=8, wrap="word", height=8
    )
    log_box.pack(fill="both", expand=True)
    log_box.tag_config("sucesso", foreground=VERDE_OK)
    log_box.tag_config("falha",   foreground=VERMELHO)
    log_box.tag_config("info",    foreground=CINZA_TEXTO)
    return log_box


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VirtualZap")
        self.geometry("660x820")
        self.minsize(660, 780)
        self.configure(bg=PRETO)

        self.driver      = None
        self.wpp_rodando = False
        self.email_rodando = False
        self.anexos = []

        # CRM (aba opcional)
        self.crm_servidor = None
        self.crm_thread   = None
        self.crm_url      = ""

        self._montar()

    # ------------------------------------------------------------------ #
    #  ESTRUTURA GERAL                                                     #
    # ------------------------------------------------------------------ #
    def _montar(self):
        # Cabeçalho
        cab = tk.Frame(self, bg=PRETO, padx=24, pady=20)
        cab.pack(fill="x")
        logo = tk.Frame(cab, bg=PRETO)
        logo.pack(anchor="w")
        tk.Label(logo, text="Virtual", bg=PRETO, fg=VERMELHO_MARCA,
                 font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(logo, text="Zap", bg=PRETO, fg=BRANCO,
                 font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(cab, text="Disparo automatizado de WhatsApp e Email",
                 bg=PRETO, fg=CINZA_TEXTO, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        # linha de destaque vermelha (identidade da marca)
        tk.Frame(self, bg=VERMELHO_MARCA, height=3).pack(fill="x", padx=24)
        tk.Frame(self, bg=CINZA_BORDA, height=1).pack(fill="x", padx=24)

        # Estilo das abas
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook",        background=PRETO, borderwidth=0)
        style.configure("TNotebook.Tab",    background=CINZA_ABA, foreground=CINZA_TEXTO,
                         font=("Segoe UI", 10, "bold"), padding=[18, 8])
        style.map("TNotebook.Tab",
                  background=[("selected", CINZA_CARD)],
                  foreground=[("selected", VERMELHO_MARCA)])

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=0, pady=0)

        aba_wpp   = tk.Frame(notebook, bg=PRETO)
        aba_email = tk.Frame(notebook, bg=PRETO)
        aba_crm   = tk.Frame(notebook, bg=PRETO)
        notebook.add(aba_wpp,   text="  💬  WhatsApp  ")
        notebook.add(aba_email, text="  ✉️   Email  ")
        notebook.add(aba_crm,   text="  📊  CRM  ")

        self._montar_aba_wpp(aba_wpp)
        self._montar_aba_email(aba_email)
        self._montar_aba_crm(aba_crm)

    # ------------------------------------------------------------------ #
    #  ABA WHATSAPP                                                        #
    # ------------------------------------------------------------------ #
    def _montar_aba_wpp(self, aba):
        corpo = tk.Frame(aba, bg=PRETO, padx=24, pady=16)
        corpo.pack(fill="both", expand=True)

        _secao(corpo, "NÚMEROS  (um por linha · ex: 5571999999999)")
        c1 = _card(corpo); c1.pack(fill="x")
        self.wpp_numeros = _texto(c1, height=6)
        self.wpp_numeros.pack(fill="x")

        _secao(corpo, "MENSAGEM  (use {nome} para personalizar)")
        c2 = _card(corpo); c2.pack(fill="x")
        self.wpp_msg = _texto(c2, height=5)
        self.wpp_msg.pack(fill="x")

        fi = tk.Frame(corpo, bg=PRETO)
        fi.pack(fill="x", pady=(12, 0))
        _label(fi, "Intervalo entre envios (seg)").pack(side="left")
        self.wpp_intervalo = tk.Spinbox(
            fi, from_=2, to=120, width=5, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, relief="flat",
            buttonbackground=CINZA_CARD, justify="center"
        )
        self.wpp_intervalo.delete(0, "end")
        self.wpp_intervalo.insert(0, "5")
        self.wpp_intervalo.pack(side="left", padx=10)

        self.wpp_btn = _botao_principal(corpo, "▶   INICIAR ENVIO", self._wpp_iniciar)

        _secao(corpo, "STATUS")
        self.wpp_log = _log_widget(corpo)


        # ------------------------------------------------------------------ #
    #  ÁREA ROLÁVEL                                                        #
    # ------------------------------------------------------------------ #
    def _criar_area_rolavel(self, aba):
        container = tk.Frame(aba, bg=PRETO)
        container.pack(fill="both", expand=True)

        canvas    = tk.Canvas(container, bg=PRETO, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        interno   = tk.Frame(canvas, bg=PRETO)

        interno.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        janela = canvas.create_window((0, 0), window=interno, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(janela, width=e.width)
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # rolagem com a roda do mouse (ativa só quando o cursor está na aba)
        def _rodinha(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _rodinha))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return interno

    # ------------------------------------------------------------------ #
    #  ABA EMAIL                                                           #
    # ------------------------------------------------------------------ #
    def _montar_aba_email(self, aba):
        interno = self._criar_area_rolavel(aba)
        corpo = tk.Frame(interno, bg=PRETO, padx=24, pady=16)
        corpo.pack(fill="both", expand=True)

        # Configuração SMTP
        _secao(corpo, "CONFIGURAÇÃO DO REMETENTE")
        cfg = _card(corpo)
        cfg.pack(fill="x")
        cfg_inner = tk.Frame(cfg, bg=CINZA_CARD, padx=12, pady=10)
        cfg_inner.pack(fill="x")

        def _row(parent, label, show=None):
            f = tk.Frame(parent, bg=CINZA_CARD)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=CINZA_CARD, fg=CINZA_TEXTO,
                     font=("Segoe UI", 9), width=16, anchor="w").pack(side="left")
            e = _entry(f, show=show)
            e.pack(side="left", fill="x", expand=True)
            e.configure(bg="#1f1f1f")
            return e

        self.email_remetente = _row(cfg_inner, "Email remetente")
        self.email_senha     = _row(cfg_inner, "Senha / App key", show="•")
        self.email_smtp      = _row(cfg_inner, "Servidor SMTP")
        self.email_smtp.insert(0, "smtp.hostinger.com")
        self.email_porta     = _row(cfg_inner, "Porta")
        self.email_porta.insert(0, "587")

        # Destinatários
        _secao(corpo, "DESTINATÁRIOS  (um por linha · formatos aceitos:)")
        _label(corpo, "  email@dominio.com   ou   Nome Completo|email@dominio.com").pack(anchor="w", pady=(0, 4))
        c1 = _card(corpo); c1.pack(fill="x")
        self.email_destinatarios = _texto(c1, height=4)
        self.email_destinatarios.pack(fill="x")

        # Assunto
        _secao(corpo, "ASSUNTO  (use {nome} para personalizar)")
        c2 = _card(corpo); c2.pack(fill="x")
        self.email_assunto = _entry(c2)
        self.email_assunto.pack(fill="x", padx=10, pady=8)

        # Corpo do email
        _secao(corpo, "CORPO DO EMAIL  (use {nome} para personalizar)")
        c3 = _card(corpo); c3.pack(fill="x")
        self.email_corpo = _texto(c3, height=5)
        self.email_corpo.pack(fill="x")

        # Anexos
        _secao(corpo, "ANEXOS  (opcional)")
        frame_anexo = tk.Frame(corpo, bg=PRETO)
        frame_anexo.pack(fill="x")
        self.lbl_anexos = _label(frame_anexo, "Nenhum arquivo selecionado")
        self.lbl_anexos.pack(side="left")
        tk.Button(
            frame_anexo, text="+ Adicionar arquivo",
            bg=CINZA_CARD, fg=VERMELHO_MARCA, relief="flat",
            font=("Segoe UI", 9), cursor="hand2", padx=8, pady=4,
            command=self._escolher_anexo
        ).pack(side="right")
        tk.Button(
            frame_anexo, text="✕ Limpar",
            bg=CINZA_CARD, fg=VERMELHO, relief="flat",
            font=("Segoe UI", 9), cursor="hand2", padx=8, pady=4,
            command=self._limpar_anexos
        ).pack(side="right", padx=(0, 6))

        # Intervalo
        fi = tk.Frame(corpo, bg=PRETO)
        fi.pack(fill="x", pady=(12, 0))
        _label(fi, "Intervalo entre envios (seg)").pack(side="left")
        self.email_intervalo = tk.Spinbox(
            fi, from_=1, to=120, width=5, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, relief="flat",
            buttonbackground=CINZA_CARD, justify="center"
        )
        self.email_intervalo.delete(0, "end")
        self.email_intervalo.insert(0, "3")
        self.email_intervalo.pack(side="left", padx=10)

        self.email_btn = _botao_principal(corpo, "▶   ENVIAR EMAILS", self._email_iniciar)

        _secao(corpo, "STATUS")
        self.email_log = _log_widget(corpo)

    # ------------------------------------------------------------------ #
    #  ABA CRM                                                             #
    # ------------------------------------------------------------------ #
    def _montar_aba_crm(self, aba):
        corpo = tk.Frame(aba, bg=PRETO, padx=24, pady=16)
        corpo.pack(fill="both", expand=True)

        _secao(corpo, "PAINEL DE LEADS")
        _label(
            corpo,
            "Funil automático com etiquetas, alerta de leads esfriando e\n"
            "saída automática por opt-out. O painel abre no navegador."
        ).pack(anchor="w", pady=(0, 4))

        # Porta do servidor local
        fp = tk.Frame(corpo, bg=PRETO)
        fp.pack(fill="x", pady=(10, 0))
        _label(fp, "Porta do painel").pack(side="left")
        self.crm_porta = tk.Spinbox(
            fp, from_=1024, to=65535, width=7, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, relief="flat",
            buttonbackground=CINZA_CARD, justify="center"
        )
        self.crm_porta.delete(0, "end")
        self.crm_porta.insert(0, "8765")
        self.crm_porta.pack(side="left", padx=10)

        self.crm_status = _label(fp, "● parado", fg=CINZA_TEXTO)
        self.crm_status.pack(side="left", padx=6)

        self.crm_btn = _botao_principal(corpo, "▶   ABRIR PAINEL DO CRM", self._crm_alternar)

        # Ações auxiliares
        fa = tk.Frame(corpo, bg=PRETO)
        fa.pack(fill="x", pady=(10, 0))
        tk.Button(
            fa, text="🌐  Abrir no navegador", bg=CINZA_CARD, fg=VERMELHO_MARCA,
            relief="flat", font=("Segoe UI", 9), cursor="hand2", padx=10, pady=5,
            command=self._crm_abrir_navegador
        ).pack(side="left")
        tk.Button(
            fa, text="📁  Pasta do projeto", bg=CINZA_CARD, fg=CINZA_TEXTO,
            relief="flat", font=("Segoe UI", 9), cursor="hand2", padx=10, pady=5,
            command=lambda: os.startfile(os.path.abspath(os.path.dirname(__file__)))
        ).pack(side="left", padx=6)

        _secao(corpo, "STATUS")
        self.crm_log = _log_widget(corpo)
        self._log(self.crm_log,
                  "O CRM roda um servidor local só na sua máquina (127.0.0.1).")
        self._log(self.crm_log,
                  "Canal e Evolution API são configurados no arquivo .env "
                  "(veja .env.example).")

    # ------------------------------------------------------------------ #
    #  CRM — controle do servidor                                          #
    # ------------------------------------------------------------------ #
    def _crm_alternar(self):
        if self.crm_servidor:
            self._crm_parar()
        else:
            self._crm_iniciar()

    def _crm_iniciar(self):
        log = lambda m: self._log(self.crm_log, m)
        try:
            import uvicorn  # noqa: F401
        except ImportError:
            messagebox.showerror(
                "Dependências do CRM",
                "O CRM precisa de bibliotecas extras.\n\n"
                "Abra o terminal na pasta do projeto e rode:\n\n"
                "    pip install -r requirements.txt"
            )
            log("❌ Dependências do CRM ausentes — rode: pip install -r requirements.txt")
            return

        try:
            porta = int(self.crm_porta.get())
        except ValueError:
            messagebox.showerror("Erro", "Porta inválida.")
            return

        self.crm_url = f"http://127.0.0.1:{porta}"
        log(f"Subindo o painel em {self.crm_url} ...")

        def _servir():
            import uvicorn
            config = uvicorn.Config(
                "crm.api:app", host="127.0.0.1", port=porta,
                log_level="warning", access_log=False,
            )
            self.crm_servidor = uvicorn.Server(config)
            # Sem isso o uvicorn tenta instalar handlers de sinal fora da thread principal.
            self.crm_servidor.install_signal_handlers = lambda: None
            try:
                self.crm_servidor.run()
            except Exception as e:
                log(f"❌ Erro no servidor do CRM: {e}")
            finally:
                self.crm_servidor = None
                self.after(0, self._crm_atualizar_botao)

        self.crm_thread = threading.Thread(target=_servir, daemon=True)
        self.crm_thread.start()

        def _confirmar():
            if self.crm_servidor:
                log(f"✅ Painel no ar: {self.crm_url}")
                self._crm_abrir_navegador()
            else:
                log("❌ O servidor não subiu. Confira se a porta está livre.")
            self._crm_atualizar_botao()

        self.after(1800, _confirmar)
        self._crm_atualizar_botao(subindo=True)

    def _crm_parar(self):
        if self.crm_servidor:
            self.crm_servidor.should_exit = True
            self._log(self.crm_log, "Parando o painel...")
        self.after(1200, self._crm_atualizar_botao)

    def _crm_abrir_navegador(self):
        if not self.crm_url:
            messagebox.showinfo("CRM", "Inicie o painel primeiro.")
            return
        import webbrowser
        webbrowser.open(self.crm_url)

    def _crm_atualizar_botao(self, subindo=False):
        ligado = bool(self.crm_servidor)
        if subindo:
            self.crm_status.config(text="● iniciando...", fg=CINZA_TEXTO)
            self.crm_btn.config(text="AGUARDE...", bg="#7a1f24")
        elif ligado:
            self.crm_status.config(text="● no ar", fg=VERDE_OK)
            self.crm_btn.config(text="■   PARAR PAINEL DO CRM", bg="#7a1f24")
        else:
            self.crm_status.config(text="● parado", fg=CINZA_TEXTO)
            self.crm_btn.config(text="▶   ABRIR PAINEL DO CRM", bg=VERMELHO_MARCA)

    # ------------------------------------------------------------------ #
    #  HELPERS DE ANEXO                                                    #
    # ------------------------------------------------------------------ #
    def _escolher_anexo(self):
        arquivos = filedialog.askopenfilenames(title="Selecionar arquivos")
        if arquivos:
            self.anexos.extend(list(arquivos))
            nomes = ", ".join(os.path.basename(a) for a in self.anexos)
            self.lbl_anexos.config(text=nomes, fg=VERMELHO_MARCA)

    def _limpar_anexos(self):
        self.anexos = []
        self.lbl_anexos.config(text="Nenhum arquivo selecionado", fg=CINZA_TEXTO)

    # ------------------------------------------------------------------ #
    #  LOG                                                                 #
    # ------------------------------------------------------------------ #
    def _log(self, widget, mensagem):
        tag = "sucesso" if mensagem.startswith("✅") else \
              "falha"   if mensagem.startswith("❌") else "info"
        def _up():
            widget.configure(state="normal")
            widget.insert("end", mensagem + "\n", tag)
            widget.see("end")
            widget.configure(state="disabled")
        self.after(0, _up)

    # ------------------------------------------------------------------ #
    #  WHATSAPP — lógica de disparo                                        #
    # ------------------------------------------------------------------ #
    def _wpp_iniciar(self):
        if self.wpp_rodando:
            messagebox.showwarning("Aviso", "Já existe um envio em andamento.")
            return
        numeros_raw = self.wpp_numeros.get("1.0", "end").strip()
        mensagem    = self.wpp_msg.get("1.0", "end").strip()
        if not numeros_raw or not mensagem:
            messagebox.showerror("Erro", "Preencha os números e a mensagem.")
            return
        numeros   = [n.strip() for n in numeros_raw.splitlines() if n.strip()]
        intervalo = int(self.wpp_intervalo.get())
        self.wpp_rodando = True
        self.wpp_btn.configure(state="disabled", text="ENVIANDO...", bg="#7a1f24")
        threading.Thread(
            target=self._wpp_processar, args=(numeros, mensagem, intervalo), daemon=True
        ).start()

    def _wpp_processar(self, numeros, mensagem, intervalo):
        log = lambda m: self._log(self.wpp_log, m)
        try:
            if self.driver is None:
                self.driver = wpp_iniciar_navegador(log)
            falhas = []
            for numero in numeros:
              
                if "|" in numero:
                    nome, numero = numero.split("|", 1)
                else:
                    nome = ""
                msg_final = mensagem.replace("{nome}", nome.strip())
                if not wpp_enviar(self.driver, numero.strip(), msg_final, log):
                    falhas.append(numero)
                time.sleep(intervalo)
            log(f"\n— Total: {len(numeros)} | ✅ {len(numeros)-len(falhas)} | ❌ {len(falhas)}")
        except Exception as e:
            log(f"❌ Erro inesperado: {e}")
        finally:
            self.wpp_rodando = False
            self.after(0, lambda: self.wpp_btn.configure(
                state="normal", text="▶   INICIAR ENVIO", bg=VERMELHO_MARCA))

    # ------------------------------------------------------------------ #
    #  EMAIL — lógica de disparo                                           #
    # ------------------------------------------------------------------ #
    def _email_iniciar(self):
        if self.email_rodando:
            messagebox.showwarning("Aviso", "Já existe um envio em andamento.")
            return
        remetente = self.email_remetente.get().strip()
        senha     = self.email_senha.get().strip()
        smtp      = self.email_smtp.get().strip()
        porta     = self.email_porta.get().strip()
        assunto   = self.email_assunto.get().strip()
        corpo     = self.email_corpo.get("1.0", "end").strip()
        dest_raw  = self.email_destinatarios.get("1.0", "end").strip()

        if not all([remetente, senha, smtp, porta, assunto, corpo, dest_raw]):
            messagebox.showerror("Erro", "Preencha todos os campos obrigatórios.")
            return

        destinatarios = []
        for linha in dest_raw.splitlines():
            linha = linha.strip()
            if not linha:
                continue
            if "|" in linha:
                nome, email = linha.split("|", 1)
            else:
                nome, email = "", linha
            destinatarios.append((nome.strip(), email.strip()))

        intervalo = int(self.email_intervalo.get())
        self.email_rodando = True
        self.email_btn.configure(state="disabled", text="ENVIANDO...", bg="#7a1f24")
        threading.Thread(
            target=self._email_processar,
            args=(smtp, int(porta), remetente, senha, assunto, corpo, destinatarios, intervalo),
            daemon=True
        ).start()

    def _email_processar(self, smtp, porta, remetente, senha, assunto, corpo, destinatarios, intervalo):
        log = lambda m: self._log(self.email_log, m)
        falhas = []
        try:
            for nome, email in destinatarios:
                ok = email_enviar(smtp, porta, remetente, senha,
                                  email, nome or email,
                                  assunto, corpo, self.anexos, log)
                if not ok:
                    falhas.append(email)
                time.sleep(intervalo)
            log(f"\n— Total: {len(destinatarios)} | ✅ {len(destinatarios)-len(falhas)} | ❌ {len(falhas)}")
        except Exception as e:
            log(f"❌ Erro inesperado: {e}")
        finally:
            self.email_rodando = False
            self.after(0, lambda: self.email_btn.configure(
                state="normal", text="▶   ENVIAR EMAILS", bg=VERMELHO_MARCA))

    # ------------------------------------------------------------------ #
    def on_close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        if self.crm_servidor:
            try:
                self.crm_servidor.should_exit = True
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()