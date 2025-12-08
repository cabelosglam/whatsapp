import gspread
from google.oauth2.service_account import Credentials
import time


# -----------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "credenciais/service_account.json"

# ID da planilha (aquele trecho entre /d/ e /edit)
SPREADSHEET_ID = "13qKgDggJWpSkWMK3ebpskPrjP_6YEXCshj_iLVzWGjg"

# Nome da aba onde estão as inscrições
SHEET_NAME = "Página1"  # mude se necessário


# -----------------------------------------------------------
# ABRIR A PLANILHA
# -----------------------------------------------------------
def abrir_planilha():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet(SHEET_NAME)


# -----------------------------------------------------------
# LER TODAS AS LINHAS DA PLANILHA
# -----------------------------------------------------------
def ler_linhas():
    ws = abrir_planilha()
    return ws.get_all_records()


# -----------------------------------------------------------
# MONITORAR NOVOS LEADS EM TEMPO REAL
# -----------------------------------------------------------
def monitorar_novos_leads(callback):
    """
    Fica verificando a planilha e sempre que encontrar um novo lead,
    chama a função callback(nome, telefone, email).
    """

    print("[GOOGLE SHEETS] Monitoramento iniciado...")

    ws = abrir_planilha()
    linhas_previas = len(ws.get_all_values())  # total inicial

    while True:
        time.sleep(5)  # verifica a cada 5 segundos

        linhas_atuais = ws.get_all_values()

        if len(linhas_atuais) > linhas_previas:
            # Nova linha foi adicionada
            nova = linhas_atuais[-1]  # última linha

            nome = nova[0]
            telefone = nova[1]
            email = nova[2] if len(nova) > 2 else ""

            print(f"[NOVA INSCRIÇÃO] {nome} | {telefone} | {email}")

            # dispara para o app.py
            callback(nome, telefone, email)

            linhas_previas = len(linhas_atuais)
