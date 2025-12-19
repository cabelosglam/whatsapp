import gspread
import json
from datetime import datetime
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "credenciais/service_account.json"

SPREADSHEET_ID = "13qKgDggJWpSkWMK3ebpskPrjP_6YEXCshj_iLVzWGjg"
SHEET_NAME = "Página1"
LOGS_SHEET_NAME = "LOGS"

PROGRESS_FILE = "sheet_progress.json"


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_tel_digits(v) -> str:
    """
    Normaliza qualquer telefone para SOMENTE DÍGITOS com país 55 quando possível.
    Aceita:
      - 6298...
      - +556298...
      - whatsapp:+556298...
    """
    if v is None:
        return ""
    s = str(v).strip()
    digits = "".join(ch for ch in s if ch.isdigit())

    # Se veio com DDD + número (10/11), prefixa 55
    if len(digits) in (10, 11):
        return "55" + digits

    # Se já veio com 55 (12/13)
    if len(digits) in (12, 13) and digits.startswith("55"):
        return digits

    # Caso raro: já veio completo sem 55 mas com 12/13
    return digits


def _canon_wpp(v) -> str:
    d = _norm_tel_digits(v)
    return f"whatsapp:+{d}" if d else ""


def abrir_planilha():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.worksheet(SHEET_NAME)


def abrir_aba(nome_aba: str):
    """Abre uma aba/worksheet pelo nome."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(nome_aba)


def ensure_logs_worksheet():
    """Garante que a aba LOGS exista e tenha cabeçalho."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(LOGS_SHEET_NAME)
    except Exception:
        ws = sh.add_worksheet(title=LOGS_SHEET_NAME, rows=2000, cols=10)

    values = ws.get_all_values()
    if not values:
        ws.append_row(
            ["TIMESTAMP", "TELEFONE", "DIRECTION", "STAGE", "BODY", "MESSAGE_SID", "TEMPLATE_SID"],
            value_input_option="USER_ENTERED",
        )
    return ws


def append_log_row(
    telefone_wpp: str,
    direction: str,
    stage: str,
    body: str,
    message_sid: str = "",
    template_sid: str = "",
):
    """Append (não sobrescreve) um log na aba LOGS."""
    ws = ensure_logs_worksheet()
    ws.append_row(
        [_now_str(), _canon_wpp(telefone_wpp) or str(telefone_wpp), direction, stage, body, message_sid, template_sid],
        value_input_option="USER_ENTERED",
    )


def get_records(nome_aba: str):
    """Retorna a lista de dicts (headers -> valores) de uma aba."""
    ws = abrir_aba(nome_aba)
    return ws.get_all_records()


def _find_tel_col(headers_l, telefone_col_names=("telefone", "phone", "celular")):
    tel_col = None
    for name in telefone_col_names:
        if name in headers_l:
            tel_col = headers_l.index(name) + 1
            break
    if tel_col is None:
        if "telefone" in headers_l:
            tel_col = headers_l.index("telefone") + 1
        else:
            raise Exception("Coluna TELEFONE não encontrada na aba.")
    return tel_col


def find_rows_by_phone(ws, telefone_wpp: str, telefone_col_names=("telefone", "phone", "celular")):
    """
    Procura linhas que tenham o telefone, comparando por DÍGITOS normalizados (evita duplicar).
    """
    valores = ws.get_all_values()
    if not valores:
        return []

    headers = [h.strip() for h in valores[0]]
    headers_l = [h.strip().lower() for h in headers]
    tel_col = _find_tel_col(headers_l, telefone_col_names)

    target = _norm_tel_digits(telefone_wpp)
    matched = []
    for i, row in enumerate(valores[1:], start=2):
        tel = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        if _norm_tel_digits(tel) == target and target:
            matched.append(i)
    return matched


def delete_lead_and_logs(telefone_wpp: str):
    """Remove o lead da Página1 e remove todas as linhas do LOGS desse telefone."""
    ws_leads = abrir_aba(SHEET_NAME)
    lead_rows = find_rows_by_phone(ws_leads, telefone_wpp)
    for r in sorted(lead_rows, reverse=True):
        ws_leads.delete_rows(r)

    ws_logs = ensure_logs_worksheet()
    log_rows = find_rows_by_phone(ws_logs, telefone_wpp, telefone_col_names=("telefone",))
    for r in sorted(log_rows, reverse=True):
        ws_logs.delete_rows(r)

    return True


def get_or_create_lead_row(ws, telefone_wpp: str, nome_padrao="profissional"):
    """
    Procura pelo telefone (coluna Telefone) e retorna:
      (row_idx, headers_l, row_values_dict)
    Se não existir, cria uma nova linha.

    IMPORTANTE: compara por dígitos normalizados para evitar duplicidade (ex.: '6298...' vs 'whatsapp:+556298...').
    """
    valores = ws.get_all_values()
    if not valores:
        raise Exception("Planilha sem cabeçalho.")

    headers = [h.strip() for h in valores[0]]
    headers_l = [h.strip().lower() for h in valores[0]]

    def col(nome):
        return headers_l.index(nome.lower()) + 1  # 1-based

    tel_col = col("telefone")
    target_digits = _norm_tel_digits(telefone_wpp)
    canonical = _canon_wpp(telefone_wpp) or str(telefone_wpp)

    # varre linhas
    for i in range(2, len(valores) + 1):
        row = ws.row_values(i)
        tel_cell = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        if target_digits and _norm_tel_digits(tel_cell) == target_digits:
            data = {}
            for idx, h in enumerate(headers_l):
                data[h] = row[idx].strip() if idx < len(row) else ""

            # opcional: normaliza o telefone na planilha para o formato canonical
            try:
                if canonical and tel_cell != canonical:
                    ws.update_cell(i, tel_col, canonical)
                    data["telefone"] = canonical
            except Exception:
                pass

            return i, headers_l, data

    # não achou -> cria
    new_row = [""] * len(headers)
    if "nome" in headers_l:
        new_row[col("nome") - 1] = nome_padrao
    new_row[tel_col - 1] = canonical
    if "data" in headers_l:
        new_row[col("data") - 1] = _now_str()
    if "stage" in headers_l:
        new_row[col("stage") - 1] = "start"
    if "updated_at" in headers_l:
        new_row[col("updated_at") - 1] = _now_str()

    ws.append_row(new_row, value_input_option="USER_ENTERED")

    row_idx = len(valores) + 1
    data = {h: "" for h in headers_l}
    data["telefone"] = canonical
    data["stage"] = "start"
    return row_idx, headers_l, data


def update_lead_fields(ws, row_idx: int, headers_l: list, **fields):
    def col(nome):
        return headers_l.index(nome.lower()) + 1

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
    """
    ws = abrir_planilha()
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
        print("Planilha vazia (ou só cabeçalho).")
        return

    headers = [h.strip().lower() for h in valores[0]]

    def col_idx(nome):
        return headers.index(nome) + 1

    nome_col = col_idx("nome")
    tel_col = col_idx("telefone")
    email_col = col_idx("email")

    if "enviado" not in headers:
        raise Exception("Crie uma coluna chamada ENVIADO no Google Sheets (no cabeçalho).")
    enviado_col = col_idx("enviado")

    enviados_agora = 0

    for row_idx in range(2, len(valores) + 1):
        row = ws.row_values(row_idx)

        nome = str(row[nome_col - 1]).strip() if len(row) >= nome_col else ""
        telefone = str(row[tel_col - 1]).strip() if len(row) >= tel_col else ""
        email = str(row[email_col - 1]).strip() if len(row) >= email_col else ""

        enviado = str(row[enviado_col - 1]).strip() if len(row) >= enviado_col else ""
        if enviado:
            continue
        if not telefone:
            continue

        print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")
        callback(nome, telefone, email)

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.update_cell(row_idx, enviado_col, f"ENVIADO {stamp}")
        enviados_agora += 1

    print(f"OK — novos processados nesta execução: {enviados_agora}")
