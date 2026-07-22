"""
Sobe o CRM do VirtualZap.

    python run_crm.py                 # painel em http://127.0.0.1:8765
    python run_crm.py --porta 9000
    python run_crm.py --host 0.0.0.0  # expõe na rede (necessário para webhook público)

O painel também pode ser aberto pela aba "CRM" do VirtualZap.py.
"""

import argparse
import threading
import webbrowser

import uvicorn

from crm import config


def main():
    parser = argparse.ArgumentParser(description="VirtualZap CRM")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--porta", type=int, default=config.PORTA)
    parser.add_argument("--sem-navegador", action="store_true",
                        help="não abre o navegador automaticamente")
    args = parser.parse_args()

    endereco = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.porta}"
    print(f"\n  VirtualZap CRM  →  {endereco}\n")

    if not args.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(endereco)).start()

    uvicorn.run("crm.api:app", host=args.host, port=args.porta, log_level="info")


if __name__ == "__main__":
    main()
