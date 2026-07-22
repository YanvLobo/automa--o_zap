"""
Detecção de opt-out ("não quero mais receber") em respostas recebidas.

A regra é conservadora de propósito: na dúvida, o lead vai para
"Respondeu — atendimento manual" e um humano decide. Falso positivo aqui
custa um lead perdido; falso negativo custa uma denúncia de spam.
"""

import re
import unicodedata
from pathlib import Path

from .config import RAIZ

# Palavras/frases que caracterizam pedido de descadastro.
PADROES_OPTOUT = [
    r"\bsair\b",
    r"\bsai\b",
    r"\bstop\b",
    r"\bcancelar?\b",
    r"\bdescadastr\w*",
    r"\bremover?\b.*\blista\b",
    r"\bme (tir[ae]|remov[ae]|exclu[ai])\b",
    r"\bn[aã]o (quero|desejo|tenho interesse)\b",
    r"\bn[aã]o me (mande|manda|envie|envia|perturbe|incomode)\b",
    r"\bn[aã]o (mande|manda|envie|envia|mandem|enviem)\b.*\b(mais|nada)\b",
    r"\bpar[ae] de (mandar|enviar|me mandar)\b",
    r"\bpar[ao]u?\b.*\bmensagens?\b",
    r"\bchega\b",
    r"\bspam\b",
    r"\bn[aã]o perturbe\b",
    r"\bsem interesse\b",
    r"\bn[aã]o tenho interesse\b",
    r"\bbloquear\b",
    r"\bvou denunciar\b",
    r"\bpare\b",
]

# Frases que parecem opt-out mas não são — evitam falso positivo.
PADROES_EXCECAO = [
    r"\bn[aã]o quero perder\b",
    r"\bn[aã]o quero mais esperar\b",
    r"\bn[aã]o entendi\b",
]

ARQUIVO_EXTRA = RAIZ / "optout_extra.txt"


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def _carregar_extras() -> list:
    """Padrões adicionais (um por linha) em optout_extra.txt, se o arquivo existir."""
    if not ARQUIVO_EXTRA.exists():
        return []
    linhas = ARQUIVO_EXTRA.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


def _compilar():
    padroes = PADROES_OPTOUT + _carregar_extras()
    return [re.compile(p, re.IGNORECASE) for p in padroes]


_REGEX_OPTOUT = _compilar()
_REGEX_EXCECAO = [re.compile(p, re.IGNORECASE) for p in PADROES_EXCECAO]


def recarregar() -> int:
    """Relê optout_extra.txt em tempo de execução. Devolve o total de padrões."""
    global _REGEX_OPTOUT
    _REGEX_OPTOUT = _compilar()
    return len(_REGEX_OPTOUT)


def eh_optout(texto: str):
    """
    Devolve (True, padrao_que_bateu) se a mensagem for um pedido de descadastro,
    (False, "") caso contrário.
    """
    if not texto:
        return False, ""
    limpo = _sem_acento(texto.strip().lower())

    for excecao in _REGEX_EXCECAO:
        if excecao.search(limpo):
            return False, ""

    for regex in _REGEX_OPTOUT:
        achou = regex.search(limpo)
        if achou:
            return True, achou.group(0)
    return False, ""
