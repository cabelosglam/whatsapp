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


import os
import json
import gspread

# ... (SEUS IMPORTS E CONSTANTES AQUI: SHEET_ID, etc.)

def monitorar_novos_leads(callback):
    """
    Lê apenas as NOVAS linhas da planilha e chama o callback para cada lead novo.

    - Usa um arquivo local sheet_state.json para guardar a última linha processada.
    - Cada nova linha preenchida na planilha é tratada como um novo lead.
    """

    print("=== INICIANDO LEITURA DA PLANILHA ===")

    # 1) Conecta na planilha (ajuste se você usa outro método)
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1  # ou sh.worksheet("Nome da aba") se você usa outra aba

    # 2) Lê todas as linhas da planilha
    valores = ws.get_all_values()  # lista de listas
    total_linhas = len(valores)

    # Arquivo onde vamos guardar o último índice processado
    state_file = "sheet_state.json"

    # 3) Recupera qual foi a última linha processada
    last_row = 1  # 1 = cabeçalho; começamos a processar da linha 2
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_row = data.get("last_row", 1)
        except Exception:
            last_row = 1

    # Se não tem nenhuma linha nova depois do cabeçalho, sai
    if total_linhas <= last_row:
        print("Nenhum novo lead para processar.")
        print("=== FINALIZADO ===")
        return

    # 4) Processa SOMENTE as linhas novas
    #    (ex: se last_row = 3, começa da linha 4)
    for idx in range(last_row + 1, total_linhas + 1):
        row = ws.row_values(idx)  # pega a linha pelo índice

        nome     = row[0] if len(row) > 0 else ""
        telefone = row[1] if len(row) > 1 else ""
        email    = row[2] if len(row) > 2 else ""

        if not telefone:
            continue  # ignora linhas sem telefone

        print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")
        callback(nome, telefone, email)

    # 5) Atualiza o arquivo de estado com a última linha existente
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"last_row": total_linhas}, f)

    print("=== FINALIZADO ===")
