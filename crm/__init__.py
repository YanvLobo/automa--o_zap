"""
VirtualZap CRM — motor de prospecção com funil automático, etiquetas e painel web.

Módulos:
    config    — configurações via .env
    db        — SQLite (schema + acesso)
    optout    — detecção de pedidos de descadastro
    channels  — adaptadores de envio (Evolution API / Selenium)
    worker    — loop de disparo (APScheduler)
    api       — FastAPI (painel + API + webhook)
"""

__version__ = "1.0.0"
