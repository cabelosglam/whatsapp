# sheet_checker.py
# Roda no Heroku Scheduler

import os
from google_sheets import monitorar_novos_leads
from app import processar_novo_lead_sheet

print("=== INICIANDO LEITURA DA PLANILHA ===")

# monitorar_novos_leads agora RECEBE um callback
monitorar_novos_leads(processar_novo_lead_sheet)

print("=== FINALIZADO ===")
