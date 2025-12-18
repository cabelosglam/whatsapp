import gspread
import json
from datetime import datetime
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
    Processa somente linhas NÃO marcadas como ENVIADO na própria planilha.
    Isso resolve o problema do Heroku Scheduler repetir envios a cada execução.
    """

    ws = abrir_planilha()

    # Lê tudo
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
        print("Planilha vazia (ou só cabeçalho).")
        return

    headers = [h.strip().lower() for h in valores[0]]

    def col_idx(nome):
        # retorna índice 1-based
        return headers.index(nome) + 1

    # Colunas esperadas
    nome_col = col_idx("nome")
    tel_col = col_idx("telefone")
    email_col = col_idx("email")

    # Coluna ENVIADO (se não existir, você precisa criar no Google Sheets)
    if "enviado" not in headers:
        raise Exception("Crie uma coluna chamada ENVIADO no Google Sheets (no cabeçalho).")
    enviado_col = col_idx("enviado")

    enviados_agora = 0

    # Começa da linha 2 (1 é cabeçalho)
    for row_idx in range(2, len(valores) + 1):
        row = ws.row_values(row_idx)

        nome = row[nome_col - 1].strip() if len(row) >= nome_col else ""
        telefone = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        email = row[email_col - 1].strip() if len(row) >= email_col else ""

        enviado = row[enviado_col - 1].strip() if len(row) >= enviado_col else ""

        # Se já marcado, ignora (não reenvia nunca)
        if enviado:
            continue

        # Se não tem telefone, ignora
        if not telefone:
            continue

        print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")
        callback(nome, telefone, email)

        # Marca como enviado (persistente!)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.update_cell(row_idx, enviado_col, f"ENVIADO {stamp}")
        enviados_agora += 1

    print(f"OK — novos processados nesta execução: {enviados_agora}")