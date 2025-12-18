import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "credenciais/service_account.json"

SPREADSHEET_ID = "13qKgDggJWpSkWMK3ebpskPrjP_6YEXCshj_iLVzWGjg"
SHEET_NAME = "Página1"


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def abrir_planilha():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)


def _get_headers(ws):
    valores = ws.get_all_values()
    if not valores or len(valores) < 1:
        raise Exception("Planilha sem cabeçalho.")
    headers_raw = valores[0]
    headers_l = [h.strip().lower() for h in headers_raw]
    return headers_l, len(headers_raw), valores


def _col(headers_l, name):
    name = name.strip().lower()
    if name not in headers_l:
        return None
    return headers_l.index(name) + 1 # 1-based

def listar_leads_para_painel(limit=500):
    """
    Retorna um dicionário no formato que o leads.html espera:
    {
      "whatsapp:+55...": {"stage": "...", "updated_at": "..."}
    }
    """
    ws = abrir_planilha()
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
        return {}

    headers = [h.strip().lower() for h in valores[0]]

    def idx(nome):
        if nome not in headers:
            return None
        return headers.index(nome)

    tel_i = idx("telefone")
    stage_i = idx("stage")
    upd_i = idx("updated_at")

    if tel_i is None:
        return {}

    leads = {}
    for r in valores[1:]:
        telefone = (r[tel_i].strip() if len(r) > tel_i else "")
        if not telefone:
            continue

        stage = (r[stage_i].strip() if stage_i is not None and len(r) > stage_i else "start")
        updated_at = (r[upd_i].strip() if upd_i is not None and len(r) > upd_i else "")

        leads[telefone] = {"stage": stage or "start", "updated_at": updated_at}

    return leads


def get_or_create_lead(ws, telefone_wpp, nome_padrao="profissional", email_padrao=""):
    """
    Procura lead pelo telefone. Se não existir, cria linha.
    Retorna: (row_idx, headers_l, lead_dict)
    """
    headers_l, width, valores = _get_headers(ws)

    tel_col = _col(headers_l, "telefone")
    if not tel_col:
        raise Exception("A planilha precisa ter a coluna 'Telefone'.")

    # Procura
    for row_idx in range(2, len(valores) + 1):
        row = ws.row_values(row_idx)
        tel = row[tel_col - 1].strip() if len(row) >= tel_col else ""
        if tel == telefone_wpp:
            lead = {h: "" for h in headers_l}
            for i, h in enumerate(headers_l):
                lead[h] = row[i].strip() if i < len(row) else ""
            return row_idx, headers_l, lead

    # Não achou -> cria linha nova
    new_row = [""] * width

    nome_col = _col(headers_l, "nome")
    email_col = _col(headers_l, "email")
    data_col = _col(headers_l, "data")
    stage_col = _col(headers_l, "stage")
    updated_col = _col(headers_l, "updated_at")

    if nome_col:
        new_row[nome_col - 1] = nome_padrao
    new_row[tel_col - 1] = telefone_wpp
    if email_col:
        new_row[email_col - 1] = email_padrao
    if data_col:
        new_row[data_col - 1] = _now_str()
    if stage_col:
        new_row[stage_col - 1] = "start"
    if updated_col:
        new_row[updated_col - 1] = _now_str()

    ws.append_row(new_row, value_input_option="USER_ENTERED")

    # Retorna a última linha criada
    row_idx = len(valores) + 1
    lead = {h: "" for h in headers_l}
    lead["telefone"] = telefone_wpp
    lead["stage"] = "start"
    return row_idx, headers_l, lead


def update_fields(ws, row_idx, headers_l, **fields):
    """
    Atualiza campos por nome de coluna.
    """
    def col(name):
        return _col(headers_l, name)

    # auto updated_at
    if _col(headers_l, "updated_at") and "updated_at" not in {k.lower() for k in fields.keys()}:
        fields["updated_at"] = _now_str()

    for k, v in fields.items():
        c = col(k)
        if not c:
            continue
        ws.update_cell(row_idx, c, "" if v is None else str(v))


def append_historico(ws, row_idx, headers_l, text):
    hist_col = _col(headers_l, "historico")
    if not hist_col:
        return
    atual = ws.cell(row_idx, hist_col).value or ""
    stamp = _now_str()
    novo = (atual + "\n" if atual else "") + f"[{stamp}] {text}"
    ws.update_cell(row_idx, hist_col, novo)
