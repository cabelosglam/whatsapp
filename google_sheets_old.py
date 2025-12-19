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

# google_sheets.py
from datetime import datetime


def abrir_aba(nome_aba: str):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(nome_aba)

def append_log_row(telefone, direction, stage, body, message_sid="", template_sid=""):
    ws_logs = abrir_aba("LOGS")
    ws_logs.append_row(
        [_now_str(), telefone, direction, stage, body, message_sid, template_sid],
        value_input_option="USER_ENTERED"
    )

def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_or_create_lead_row(ws, telefone_wpp: str, nome_padrao="profissional"):
    """
    Procura pelo telefone (coluna Telefone) e retorna:
      (row_idx, headers_map, row_values_dict)
    Se não existir, cria uma nova linha.
    """
    valores = ws.get_all_values()
    if not valores:
        raise Exception("Planilha sem cabeçalho.")

    headers = [h.strip() for h in valores[0]]
    headers_l = [h.strip().lower() for h in valores[0]]

    def col(nome):
        return headers_l.index(nome.lower()) + 1  # 1-based

    tel_col = col("telefone")

    # varre linhas
    for i in range(2, len(valores) + 1):
        row = ws.row_values(i)
        tel = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        if tel == telefone_wpp:
            data = {}
            for idx, h in enumerate(headers_l):
                data[h] = row[idx].strip() if idx < len(row) else ""
            return i, headers_l, data

    # não achou -> cria
    # garante que tenha colunas mínimas
    def safe_get(nome, default=""):
        return default if nome.lower() in headers_l else None

    new_row = [""] * len(headers)
    # Preenche campos base se existirem
    if "nome" in headers_l:
        new_row[col("nome") - 1] = nome_padrao
    new_row[tel_col - 1] = telefone_wpp
    if "data" in headers_l:
        new_row[col("data") - 1] = _now_str()
    if "stage" in headers_l:
        new_row[col("stage") - 1] = "start"
    if "updated_at" in headers_l:
        new_row[col("updated_at") - 1] = _now_str()

    ws.append_row(new_row, value_input_option="USER_ENTERED")

    # retorna a última linha
    row_idx = len(valores) + 1
    data = {h: "" for h in headers_l}
    data["telefone"] = telefone_wpp
    data["stage"] = "start"
    return row_idx, headers_l, data


def update_lead_fields(ws, row_idx: int, headers_l: list, **fields):
    """
    Atualiza campos por nome de coluna (case-insensitive).
    Ex: update_lead_fields(ws, row_idx, headers_l, stage="nutricao", updated_at="...", last_inbound="sim")
    """
    def col(nome):
        return headers_l.index(nome.lower()) + 1

    # sempre atualiza UPDATED_AT se existir e não foi passado
    if "updated_at" in headers_l and "updated_at" not in [k.lower() for k in fields.keys()]:
        fields["updated_at"] = _now_str()

    for k, v in fields.items():
        key = k.lower()
        if key not in headers_l:
            continue
        ws.update_cell(row_idx, col(key), str(v))

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