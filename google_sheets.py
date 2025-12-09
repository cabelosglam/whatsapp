import gspread
import json
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "credenciais/service_account.json"

SPREADSHEET_ID = "13qKgDggJWpSkWMK3ebpskPrjP_6YEXCshj_iLVzWGjg"
SHEET_NAME = "Página1"

PROGRESS_FILE = "sheet_progress.json"


def abrir_planilha():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet(SHEET_NAME)


def ler_linhas():
    ws = abrir_planilha()
    return ws.get_all_records()


def carregar_progresso():
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"last_row": 1}


def salvar_progresso(data):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def monitorar_novos_leads(callback):
    """
    Lê a planilha e dispara callback(nome, telefone, email)
    para linhas novas.
    """

    ws = abrir_planilha()
    dados = ws.get_all_records()

    progresso = carregar_progresso()
    last_row = progresso.get("last_row", 1)

    novos = dados[last_row:]  # somente linhas novas

    for linha in novos:
        nome = linha.get("Nome")
        telefone = linha.get("Telefone")
        email = linha.get("Email")

        if telefone:
            callback(nome, telefone, email)

    progresso["last_row"] = len(dados)
    salvar_progresso(progresso)
