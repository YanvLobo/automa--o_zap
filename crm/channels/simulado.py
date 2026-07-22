"""
Canal de teste: não envia nada, só registra no log.

Serve para validar o funil, os intervalos e o painel inteiro sem gastar
número de WhatsApp nem correr risco de bloqueio.
"""

import logging

from .base import Canal, ResultadoEnvio

log = logging.getLogger("crm.canal.simulado")


class CanalSimulado(Canal):
    nome = "simulado"
    recebe_respostas = False

    def enviar(self, telefone: str, texto: str) -> ResultadoEnvio:
        preview = texto.replace("\n", " ")[:80]
        log.info("[SIMULADO] -> %s: %s", telefone, preview)
        return ResultadoEnvio(True, "simulado (nenhuma mensagem real foi enviada)")

    def status(self) -> dict:
        return {
            "nome": self.nome,
            "pronto": True,
            "detalhe": "Modo de teste — nada é enviado de verdade.",
            "recebe_respostas": False,
        }
