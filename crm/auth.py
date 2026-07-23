"""
Login do painel — usuário/senha configurados pelo próprio painel (guardados
no banco, tabela `configuracoes`), sem depender de Caddy/proxy externo.

Sessão simples: token aleatório em memória, associado a um cookie httponly.
Reiniciar o processo derruba todas as sessões (usuário loga de novo) — trade-off
aceitável para um painel de operador único/pequena equipe.
"""

import hashlib
import hmac
import os
import secrets

from . import db

COOKIE = "crm_sessao"
_ITERACOES = 260_000

_sessoes: set[str] = set()


def _hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, _ITERACOES)
    return f"pbkdf2${_ITERACOES}${salt.hex()}${h.hex()}"


def _verificar_hash(senha: str, armazenado: str) -> bool:
    try:
        _, iteracoes, salt_hex, hash_hex = armazenado.split("$")
        salt = bytes.fromhex(salt_hex)
        h = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, int(iteracoes))
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def configurado() -> bool:
    return bool(db.obter_config("auth_senha_hash"))


def definir_credenciais(usuario: str, senha: str) -> None:
    db.salvar_config({"auth_usuario": usuario.strip(), "auth_senha_hash": _hash_senha(senha)})
    _sessoes.clear()  # trocar a senha derruba sessões antigas


def verificar_login(usuario: str, senha: str) -> bool:
    hash_salvo = db.obter_config("auth_senha_hash")
    if not hash_salvo:
        return False
    usuario_salvo = db.obter_config("auth_usuario")
    return usuario.strip() == usuario_salvo and _verificar_hash(senha, hash_salvo)


def criar_sessao() -> str:
    token = secrets.token_urlsafe(32)
    _sessoes.add(token)
    return token


def sessao_valida(token: str | None) -> bool:
    return bool(token) and token in _sessoes


def encerrar_sessao(token: str | None) -> None:
    _sessoes.discard(token)
