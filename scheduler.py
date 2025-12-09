from google_sheets import monitorar_novos_leads
from app import processar_novo_lead_sheet

# Chama o monitoramento apenas uma vez.
# O Heroku Scheduler executará este arquivo periodicamente.
monitorar_novos_leads(processar_novo_lead_sheet)
