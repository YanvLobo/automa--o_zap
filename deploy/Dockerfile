# Imagem do VirtualZap CRM para rodar na VPS (sem Selenium/Tkinter).
FROM python:3.12-slim

WORKDIR /app

# Dependências
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Código
COPY crm ./crm
COPY run_crm.py .

# O banco fica num volume persistente
ENV CRM_HOST=0.0.0.0 \
    CRM_PORTA=8765 \
    CRM_BANCO=/data/crm_leads.db

EXPOSE 8765
VOLUME ["/data"]

CMD ["python", "run_crm.py", "--host", "0.0.0.0", "--sem-navegador"]
