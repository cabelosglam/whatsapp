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


def _safe_str(v):
    if v is None:
        return ""
    return str(v).strip()


def _norm_tel_digits(v) -> str:
    """
    Normaliza qualquer telefone para SOMENTE DÍGITOS com país 55 quando possível.
    Aceita:
      - 6298...
      - +556298...
      - whatsapp:+556298...
    """
    s = _safe_str(v)
    digits = "".join(ch for ch in s if ch.isdigit())


    # BR: se veio sem o 9 (55 + DDD + 8 dígitos = 12), insere "9" após o DDD
    if len(digits) == 12 and digits.startswith("55"):
        digits = digits[:4] + "9" + digits[4:]

    # DDD + número (10/11) -> prefixa 55
    if len(digits) in (10, 11):
        return "55" + digits

    # Já veio com 55 (12/13)
    if len(digits) in (12, 13) and digits.startswith("55"):
        return digits

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
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(nome_aba)


def ensure_logs_worksheet():
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


def append_log_row(telefone_wpp: str, direction: str, stage: str, body: str, message_sid: str = "", template_sid: str = ""):
    ws = ensure_logs_worksheet()
    ws.append_row(
        [_now_str(), _canon_wpp(telefone_wpp) or _safe_str(telefone_wpp), direction, stage, body, message_sid, template_sid],
        value_input_option="USER_ENTERED",
    )


def _headers(ws):
    valores = ws.get_all_values()
    if not valores:
        raise Exception("Planilha sem cabeçalho.")
    headers = [h.strip() for h in valores[0]]
    headers_l = [h.strip().lower() for h in headers]
    return valores, headers, headers_l


def _col(headers_l, nome):
    return headers_l.index(nome.lower()) + 1


def _row_to_dict(headers_l, row_values):
    d = {}
    for idx, h in enumerate(headers_l):
        d[h] = _safe_str(row_values[idx]) if idx < len(row_values) else ""
    return d


def _score_row(data: dict) -> int:
    """
    Escolhe a 'melhor' linha quando existem duplicadas.
    Prioriza:
      1) nome preenchido e diferente de 'profissional'
      2) email preenchido
      3) mais colunas preenchidas
    """
    score = 0
    nome = (data.get("nome") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()

    if nome and nome != "profissional":
        score += 100
    if email:
        score += 20

    # densidade de dados
    filled = sum(1 for v in data.values() if str(v).strip())
    score += min(filled, 30)

    return score


def dedupe_rows_by_phone(ws, telefone_any: str):
    """
    Se existirem múltiplas linhas com o mesmo telefone (comparando por dígitos),
    mantém a melhor e apaga o resto. Retorna (kept_row_idx, headers_l, kept_data).
    """
    valores, headers, headers_l = _headers(ws)
    tel_col = _col(headers_l, "telefone")

    target = _norm_tel_digits(telefone_any)
    if not target:
        return None

    matches = []
    for i in range(2, len(valores) + 1):
        row = ws.row_values(i)
        tel_cell = _safe_str(row[tel_col - 1]) if len(row) >= tel_col else ""
        if _norm_tel_digits(tel_cell) == target:
            data = _row_to_dict(headers_l, row)
            matches.append((i, data))

    if not matches:
        return None

    # escolhe melhor
    matches_sorted = sorted(matches, key=lambda x: _score_row(x[1]), reverse=True)
    keep_idx, keep_data = matches_sorted[0]

    # normaliza telefone na linha mantida
    canonical = _canon_wpp(telefone_any) or _canon_wpp(keep_data.get("telefone")) or keep_data.get("telefone") or ""
    if canonical:
        try:
            ws.update_cell(keep_idx, tel_col, canonical)
            keep_data["telefone"] = canonical
        except Exception:
            pass

    # apaga duplicadas (de baixo pra cima)
    to_delete = [idx for idx, _ in matches_sorted[1:]]
    for r in sorted(to_delete, reverse=True):
        try:
            ws.delete_rows(r)
        except Exception:
            pass

    return keep_idx, headers_l, keep_data


def get_or_create_lead_row(ws, telefone_wpp: str, nome_padrao="profissional"):
    """
    Procura pelo telefone por dígitos normalizados; se houver duplicados, deduplica.
    Se não existir, cria.
    """
    # 1) se já existe (ou duplicado), deduplica e retorna
    deduped = dedupe_rows_by_phone(ws, telefone_wpp)
    if deduped:
        return deduped

    # 2) não existe -> cria
    valores, headers, headers_l = _headers(ws)
    tel_col = _col(headers_l, "telefone")

    def set_if_exists(row, colname, value):
        if colname in headers_l:
            row[_col(headers_l, colname) - 1] = value

    canonical = _canon_wpp(telefone_wpp) or _safe_str(telefone_wpp)
    new_row = [""] * len(headers)
    set_if_exists(new_row, "nome", nome_padrao)
    new_row[tel_col - 1] = canonical
    set_if_exists(new_row, "data", _now_str())
    set_if_exists(new_row, "stage", "start")
    set_if_exists(new_row, "updated_at", _now_str())

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


def find_rows_by_phone(ws, telefone_any: str, telefone_col_names=("telefone", "phone", "celular")):
    valores, headers, headers_l = _headers(ws)
    tel_col = _col(headers_l, "telefone")
    target = _norm_tel_digits(telefone_any)
    matched = []
    for i, row in enumerate(valores[1:], start=2):
        tel = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        if _norm_tel_digits(tel) == target and target:
            matched.append(i)
    return matched


def delete_lead_and_logs(telefone_wpp: str):
    ws_leads = abrir_aba(SHEET_NAME)
    lead_rows = find_rows_by_phone(ws_leads, telefone_wpp)
    for r in sorted(lead_rows, reverse=True):
        ws_leads.delete_rows(r)

    ws_logs = ensure_logs_worksheet()
    log_rows = find_rows_by_phone(ws_logs, telefone_wpp, telefone_col_names=("telefone",))
    for r in sorted(log_rows, reverse=True):
        ws_logs.delete_rows(r)
    return True


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

        nome = _safe_str(row[nome_col - 1]) if len(row) >= nome_col else ""
        telefone = _safe_str(row[tel_col - 1]) if len(row) >= tel_col else ""
        email = _safe_str(row[email_col - 1]) if len(row) >= email_col else ""

        enviado = _safe_str(row[enviado_col - 1]) if len(row) >= enviado_col else ""
        if enviado:
            continue
        if not telefone:
            continue

        print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")
        callback(nome, telefone, email)

        stamp = _now_str()
        ws.update_cell(row_idx, enviado_col, f"ENVIADO {stamp}")
        enviados_agora += 1

    print(f"OK — novos processados nesta execução: {enviados_agora}")
