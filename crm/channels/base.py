"""Contrato que todo canal de envio precisa cumprir."""

from dataclasses import dataclass


@dataclass
class ResultadoEnvio:
    sucesso: bool
    detalhe: str = ""
    id_externo: str = ""


class Canal:
    """Interface do canal. Subclasses implementam ao menos `enviar`."""

    nome = "base"
    #: O canal consegue receber respostas (webhook)? Define se as regras de
    #: opt-out / roteamento automático funcionam sozinhas.
    recebe_respostas = False

    def enviar(self, telefone: str, texto: str) -> ResultadoEnvio:
        raise NotImplementedError

    def status(self) -> dict:
        """Diagnóstico exibido no painel."""
        return {"nome": self.nome, "pronto": True, "detalhe": "", "recebe_respostas": self.recebe_respostas}

    def encerrar(self) -> None:
        """Libera recursos (driver, sessão HTTP)."""
        pass
