"""
Adaptadores de canal de envio.

O CRM nunca fala direto com WhatsApp: fala com um Canal. Trocar de Evolution
API para Selenium (ou para qualquer outro provedor no futuro) é trocar uma
variável no .env — nenhum código do funil muda.
"""

from .base import Canal, ResultadoEnvio
from .simulado import CanalSimulado

_cache = {}


def obter_canal(nome=None) -> Canal:
    """Devolve (e memoriza) o canal configurado. 'nome' sobrescreve o .env."""
    from .. import config

    nome = (nome or config.CANAL).lower()
    if nome in _cache:
        return _cache[nome]

    if nome == "evolution":
        from .evolution import CanalEvolution
        canal = CanalEvolution()
    elif nome == "selenium":
        from .selenium_wa import CanalSelenium
        canal = CanalSelenium()
    else:
        canal = CanalSimulado()

    _cache[nome] = canal
    return canal


def limpar_cache() -> None:
    """Força a recriação dos canais (usado ao trocar de canal em execução)."""
    for canal in _cache.values():
        try:
            canal.encerrar()
        except Exception:
            pass
    _cache.clear()


__all__ = ["Canal", "ResultadoEnvio", "obter_canal", "limpar_cache"]
