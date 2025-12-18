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
    Lê apenas as NOVAS linhas da planilha e chama o callback para cada lead novo.
    Guarda a última linha processada em PROGRESS_FILE (json).
    """

    print("=== INICIANDO LEITURA DA PLANILHA ===")

    ws = abrir_planilha()

    # Lê todas as linhas (inclui cabeçalho)
    valores = ws.get_all_values()
    total_linhas = len(valores)

    # Recupera última linha processada (1 = cabeçalho)
    state = carregar_progresso()
    last_row = int(state.get("last_row", 1))

    # Se não tem linha nova
    if total_linhas <= last_row:
        print("Nenhum novo lead para processar.")
        print("=== FINALIZADO ===")
        return

    # Processa somente as linhas novas (a partir da próxima)
    for idx in range(last_row + 1, total_linhas + 1):
        row = ws.row_values(idx)

        nome     = row[0].strip() if len(row) > 0 else ""
        telefone = row[1].strip() if len(row) > 1 else ""
        email    = row[2].strip() if len(row) > 2 else ""

        if not telefone:
            continue

        print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")
        callback(nome, telefone, email)

    # Atualiza o progresso com a última linha existente
    salvar_progresso({"last_row": total_linhas})

    print("=== FINALIZADO ===")
