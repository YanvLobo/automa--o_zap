"""
Interface gráfica para envio automatizado de mensagens via WhatsApp Web.

Requisitos:
    pip install selenium webdriver-manager

Como usar:
    1. Rode este arquivo: python interface_whatsapp.py
    2. Cole os números (um por linha) na caixa de números.
    3. Escreva a mensagem na caixa de mensagem.
    4. Clique em "Iniciar Envio".
    5. Na primeira vez, uma janela do Chrome vai abrir pedindo para escanear
       o QR Code do WhatsApp. Nas próximas vezes, ele entra direto.
"""

import os
import time
import threading
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ----------------------- LÓGICA DE ENVIO (Selenium) -----------------------

def iniciar_navegador(log):
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
    log("WhatsApp Web carregado com sucesso.\n")
    return driver


def enviar_mensagem(driver, numero, mensagem, log):
    numero = numero.replace("+", "").replace(" ", "").replace("-", "")
    texto_codificado = urllib.parse.quote(mensagem)
    url = f"https://web.whatsapp.com/send?phone={numero}&text={texto_codificado}"
    driver.get(url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((
                By.XPATH,
                '//div[@contenteditable="true"][@data-tab="10"] | //footer//div[@contenteditable="true"]'
            ))
        )
        botao_enviar = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((
                By.XPATH,
                '//span[@data-icon="send" or @data-icon="wds-ic-send-filled"]/ancestor::button'
            ))
        )
        time.sleep(1)
        botao_enviar.click()
        time.sleep(2)
        log(f"✅ Mensagem enviada para {numero}")
        return True
    except Exception:
        log(f"❌ Falha ao enviar para {numero} (número inválido ou sem WhatsApp)")
        return False


# ------------------------------- INTERFACE -------------------------------

# ------------------------------- PALETA -------------------------------
PRETO = "#0a0a0a"
CINZA_CARD = "#161616"
CINZA_BORDA = "#2a2a2a"
VERDE_LIMAO = "#c8ff3d"
VERDE_LIMAO_HOVER = "#b3e635"
BRANCO = "#f5f5f5"
CINZA_TEXTO = "#9a9a9a"
VERMELHO = "#ff5c5c"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VirtualZap — Envio Automático")
        self.geometry("640x760")
        self.minsize(640, 760)
        self.configure(bg=PRETO)

        self.driver = None
        self.enviando = False

        self._montar_interface()

    # --------------------------- COMPONENTES UI ---------------------------

    def _campo_titulo(self, parent, texto):
        tk.Label(
            parent, text=texto, bg=PRETO, fg=VERDE_LIMAO,
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(0, 6))

    def _card(self, parent):
        card = tk.Frame(parent, bg=CINZA_CARD, highlightbackground=CINZA_BORDA,
                         highlightthickness=1, bd=0)
        return card

    def _montar_interface(self):
        # ---------- Topo / Cabeçalho ----------
        topo = tk.Frame(self, bg=PRETO, padx=24, pady=24)
        topo.pack(fill="x")

        tk.Label(
            topo, text="VirtualZap",
            bg=PRETO, fg=BRANCO, font=("Segoe UI", 22, "bold")
        ).pack(anchor="w")
        tk.Label(
            topo, text="Disparo automatizado de mensagens via WhatsApp Web",
            bg=PRETO, fg=CINZA_TEXTO, font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(2, 0))

        linha = tk.Frame(self, bg=CINZA_BORDA, height=1)
        linha.pack(fill="x", padx=24)

        # ---------- Corpo ----------
        corpo = tk.Frame(self, bg=PRETO, padx=24, pady=20)
        corpo.pack(fill="both", expand=True)

        # Card: Números
        self._campo_titulo(corpo, "NÚMEROS  (um por linha, com DDI+DDD, ex: 5571999999999)")
        card_numeros = self._card(corpo)
        card_numeros.pack(fill="x", pady=(0, 18))
        self.txt_numeros = tk.Text(
            card_numeros, height=6, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, insertbackground=VERDE_LIMAO,
            relief="flat", padx=12, pady=10, wrap="word"
        )
        self.txt_numeros.pack(fill="x")

        # Card: Mensagem
        self._campo_titulo(corpo, "MENSAGEM")
        card_msg = self._card(corpo)
        card_msg.pack(fill="x", pady=(0, 18))
        self.txt_mensagem = tk.Text(
            card_msg, height=6, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, insertbackground=VERDE_LIMAO,
            relief="flat", padx=12, pady=10, wrap="word"
        )
        self.txt_mensagem.pack(fill="x")

        # Intervalo
        frame_intervalo = tk.Frame(corpo, bg=PRETO)
        frame_intervalo.pack(fill="x", pady=(0, 20))
        tk.Label(
            frame_intervalo, text="Intervalo entre envios (segundos)",
            bg=PRETO, fg=CINZA_TEXTO, font=("Segoe UI", 9)
        ).pack(side="left")
        self.spin_intervalo = tk.Spinbox(
            frame_intervalo, from_=2, to=60, width=5, font=("Segoe UI", 10),
            bg=CINZA_CARD, fg=BRANCO, insertbackground=VERDE_LIMAO,
            relief="flat", buttonbackground=CINZA_CARD, highlightthickness=1,
            highlightbackground=CINZA_BORDA, justify="center"
        )
        self.spin_intervalo.delete(0, "end")
        self.spin_intervalo.insert(0, "5")
        self.spin_intervalo.pack(side="left", padx=10)

        # Botão iniciar
        self.btn_iniciar = tk.Button(
            corpo, text="▶   INICIAR ENVIO",
            bg=VERDE_LIMAO, fg=PRETO, activebackground=VERDE_LIMAO_HOVER,
            activeforeground=PRETO, font=("Segoe UI", 11, "bold"),
            relief="flat", padx=10, pady=12, cursor="hand2",
            command=self._iniciar_envio_thread
        )
        self.btn_iniciar.pack(fill="x", pady=(0, 20))
        self.btn_iniciar.bind("<Enter>", lambda e: self.btn_iniciar.config(bg=VERDE_LIMAO_HOVER))
        self.btn_iniciar.bind("<Leave>", lambda e: self.btn_iniciar.config(
            bg=VERDE_LIMAO if not self.enviando else "#5a6b2e"))

        # Status / Log
        self._campo_titulo(corpo, "STATUS")
        card_log = self._card(corpo)
        card_log.pack(fill="both", expand=True)
        self.txt_log = scrolledtext.ScrolledText(
            card_log, font=("Consolas", 9), state="disabled",
            bg=CINZA_CARD, fg="#c8c8c8", relief="flat",
            padx=12, pady=10, wrap="word"
        )
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_config("sucesso", foreground=VERDE_LIMAO)
        self.txt_log.tag_config("falha", foreground=VERMELHO)
        self.txt_log.tag_config("info", foreground=CINZA_TEXTO)

    def log(self, mensagem):
        tag = "info"
        if mensagem.startswith("✅"):
            tag = "sucesso"
        elif mensagem.startswith("❌"):
            tag = "falha"

        def _atualizar():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", mensagem + "\n", tag)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        self.after(0, _atualizar)

    def _iniciar_envio_thread(self):
        if self.enviando:
            messagebox.showwarning("Aviso", "Já existe um envio em andamento.")
            return

        numeros_raw = self.txt_numeros.get("1.0", "end").strip()
        mensagem = self.txt_mensagem.get("1.0", "end").strip()

        if not numeros_raw or not mensagem:
            messagebox.showerror("Erro", "Preencha os números e a mensagem antes de iniciar.")
            return

        numeros = [n.strip() for n in numeros_raw.splitlines() if n.strip()]
        intervalo = int(self.spin_intervalo.get())

        self.enviando = True
        self.btn_iniciar.configure(state="disabled", text="ENVIANDO...", bg="#5a6b2e")

        thread = threading.Thread(target=self._processar_envio, args=(numeros, mensagem, intervalo), daemon=True)
        thread.start()

    def _processar_envio(self, numeros, mensagem, intervalo):
        try:
            if self.driver is None:
                self.driver = iniciar_navegador(self.log)

            falhas = []
            for numero in numeros:
                sucesso = enviar_mensagem(self.driver, numero, mensagem, self.log)
                if not sucesso:
                    falhas.append(numero)
                time.sleep(intervalo)

            self.log("\n--- Resumo ---")
            self.log(f"Total: {len(numeros)} | Sucesso: {len(numeros) - len(falhas)} | Falhas: {len(falhas)}")
            if falhas:
                self.log(f"Números com falha: {', '.join(falhas)}")

        except Exception as e:
            self.log(f"Erro inesperado: {e}")
        finally:
            self.enviando = False
            self.after(0, lambda: self.btn_iniciar.configure(
                state="normal", text="▶   INICIAR ENVIO", bg=VERDE_LIMAO))

    def on_close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()