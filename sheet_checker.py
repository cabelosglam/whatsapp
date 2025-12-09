import os
import time
from google_sheets import buscar_novos_leads
from twilio.rest import Client

# ===============================
# VARIÁVEIS DO HEROKU
# ===============================
ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
FROM_WPP = os.getenv("FROM_WPP")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ===============================
# BUSCAR NOVOS LEADS NA PLANILHA
# ===============================
novos = buscar_novos_leads()

if not novos:
    print("[SHEET] Nenhum novo lead encontrado.")
    exit()

for lead in novos:
    nome = lead["nome"]
    telefone = lead["telefone"]

    # Corrigir número para formato do WhatsApp
    telefone = telefone.replace(" ", "").replace("-", "")
    if not telefone.startswith("55"):
        telefone = "55" + telefone

    destino = f"whatsapp:+{telefone}"

    print(f"[ENVIANDO PARA WHATSAPP] {nome} | {destino}")

    # ===============================
    # ENVIAR PRIMEIRA MENSAGEM
    # ===============================
    try:
        client.messages.create(
            from_=FROM_WPP,
            to=destino,
            content_sid="HXfb376726c199d4fc794977c6d62c4037"  # Mensagem 1
        )
        print("[OK] Mensagem enviada com sucesso.")

    except Exception as e:
        print("[ERRO AO ENVIAR]", e)

    time.sleep(1)
