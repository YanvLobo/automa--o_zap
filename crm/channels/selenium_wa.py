"""
Canal Selenium — reaproveita o motor de envio já existente no VirtualZap.py
(WhatsApp Web + perfil persistente em ./perfil_whatsapp).

Limitação importante: o Selenium só ENVIA. Ele não recebe eventos, então as
regras automáticas de opt-out e de roteamento por resposta não disparam
sozinhas neste canal — você move o lead de etiqueta pelo painel. Para o funil
100% automático, use o canal 'evolution'.

Atenção: o Chrome só aceita um processo por perfil. Se a aba WhatsApp do
VirtualZap já estiver com o navegador aberto, feche-a antes de usar este canal
(ou aponte CRM_CANAL para 'evolution'/'simulado').
"""

import logging
import sys
import threading
from pathlib import Path

from .base import Canal, ResultadoEnvio

log = logging.getLogger("crm.canal.selenium")

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


class CanalSelenium(Canal):
    nome = "selenium"
    recebe_respostas = False

    def __init__(self):
        self._driver = None
        self._lock = threading.Lock()
        self._ultimo_erro = ""

    # ------------------------------------------------------------------ #
    def _garantir_driver(self):
        if self._driver is not None:
            return self._driver
        import VirtualZap  # importado sob demanda: evita exigir selenium quando não se usa este canal

        self._driver = VirtualZap.wpp_iniciar_navegador(lambda m: log.info("%s", m))
        return self._driver

    # ------------------------------------------------------------------ #
    def enviar(self, telefone: str, texto: str) -> ResultadoEnvio:
        import VirtualZap

        with self._lock:
            try:
                driver = self._garantir_driver()
            except Exception as e:
                self._ultimo_erro = str(e)
                return ResultadoEnvio(False, f"Não foi possível abrir o WhatsApp Web: {e}")

            try:
                ok = VirtualZap.wpp_enviar(driver, telefone, texto, lambda m: log.info("%s", m))
            except Exception as e:
                self._ultimo_erro = str(e)
                self._driver = None  # sessão morreu; força reabrir no próximo envio
                return ResultadoEnvio(False, f"Erro no Selenium: {e}")

        return ResultadoEnvio(ok, "enviado" if ok else "WhatsApp Web recusou o envio")

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        return {
            "nome": self.nome,
            "pronto": self._driver is not None,
            "recebe_respostas": False,
            "detalhe": self._ultimo_erro or (
                "Navegador aberto." if self._driver
                else "O navegador abre no primeiro disparo (pode pedir QR Code)."
            ),
        }

    def encerrar(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
