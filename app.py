from flask import Flask, render_template, request, jsonify, redirect, url_for
from twilio.rest import Client
from dotenv import load_dotenv
import os
import json
import time
import threading
from datetime import datetime

# -------------------------------------------------------------
#  CARREGAR VARIÁVEIS DE AMBIENTE (.env)
# -------------------------------------------------------------
load_dotenv()

# -------------------------------------------------------------
#  GOOGLE SHEETS como BANCO (Página1 + LOGS)
# -------------------------------------------------------------
from google_sheets import (
    abrir_planilha,
    abrir_aba,
    ensure_logs_worksheet,
    append_log_row,
    get_or_create_lead_row,
    update_lead_fields,
    delete_lead_and_logs,
    LOGS_SHEET_NAME,
    SHEET_NAME,
)

app = Flask(__name__)

# -------------------------------------------------------------
#  TWILIO
# -------------------------------------------------------------
ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
FROM_WPP = os.getenv("FROM_WPP")  # Ex: whatsapp:+14155238886

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# -------------------------------------------------------------
#  MEMÓRIA LOCAL (curta) PARA OS LEADS (por dyno)
# -------------------------------------------------------------
lead_status = {}

# -------------------------------------------------------------
#  HELPERS
# -------------------------------------------------------------
def safe_str(v):
    """Sheets às vezes retorna int/float/None. Sempre normalize para string."""
    if v is None:
        return ""
    return str(v).strip()

def normalize_phone_digits(phone: str) -> str:
    """Retorna apenas dígitos; aplica regra Brasil."""
    digits = "".join(filter(str.isdigit, safe_str(phone)))

    # 10 ou 11 dígitos (DDD + número) -> prefixa 55
    if len(digits) in (10, 11):
        return "55" + digits

    # Já veio com 55
    if len(digits) in (12, 13):
        return digits

    return ""

def normalize_to_wpp(phone_any) -> str:
    """Converte '6298...' ou '+5562...' ou 'whatsapp:+55...' em 'whatsapp:+55...'."""
    s = safe_str(phone_any)
    if not s:
        return ""
    if s.startswith("whatsapp:"):
        # garante que esteja no padrão whatsapp:+<digits>
        parts = s.split(":", 1)
        rest = parts[1]
        digits = normalize_phone_digits(rest)
        return f"whatsapp:+{digits}" if digits else s
    # sem whatsapp:
    digits = normalize_phone_digits(s)
    return f"whatsapp:+{digits}" if digits else ""

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# -------------------------------------------------------------
#  ANTI-DUPLICIDADE (MessageSid)
# -------------------------------------------------------------
PROCESSED_SIDS_FILE = "processed_sids.json"

def load_processed_sids():
    if os.path.exists(PROCESSED_SIDS_FILE):
        try:
            with open(PROCESSED_SIDS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_processed_sids(sids_set):
    try:
        with open(PROCESSED_SIDS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sids_set), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[WARN] Falha ao salvar processed_sids:", e)

processed_sids = load_processed_sids()

def is_duplicate_message(message_sid: str) -> bool:
    if not message_sid:
        return False
    if message_sid in processed_sids:
        return True
    processed_sids.add(message_sid)

    # limita crescimento
    if len(processed_sids) > 5000:
        processed_sids_list = list(processed_sids)[-2000:]
        processed_sids.clear()
        processed_sids.update(processed_sids_list)

    save_processed_sids(processed_sids)
    return False

# -------------------------------------------------------------
#  LOG PERSISTENTE NO SHEETS (Página1 + LOGS)
# -------------------------------------------------------------
def salvar_log(number_wpp: str, body: str, stage: str, direction: str, message_sid: str = "", template_sid: str = ""):
    """
    Salva log PERSISTENTE no Google Sheets (aba LOGS) e atualiza a linha do lead na Página1.
    number_wpp: 'whatsapp:+55...'
    """
    number_wpp = normalize_to_wpp(number_wpp)
    stage = safe_str(stage) or "start"
    body = safe_str(body)

    try:
        # 1) append no LOGS
        append_log_row(
            telefone_wpp=number_wpp,
            direction=direction,
            stage=stage,
            body=body,
            message_sid=message_sid,
            template_sid=template_sid
        )

        # 2) update da Página1
        ws = abrir_planilha()
        row_idx, headers_l, _ = get_or_create_lead_row(ws, number_wpp)

        fields = {"stage": stage}
        if direction == "inbound":
            fields.update({"last_inbound": body, "last_inbound_at": now_str()})
        else:
            fields.update({"last_outbound": body, "last_outbound_at": now_str()})

        if template_sid:
            fields["last_template_sid"] = template_sid
        if message_sid:
            fields["last_message_sid"] = message_sid

        update_lead_fields(ws, row_idx, headers_l, **fields)

    except Exception as e:
        print("[ERRO AO SALVAR LOG NO SHEETS]", e)

# -------------------------------------------------------------
#  FOLLOW-UP (se não responder)
# -------------------------------------------------------------
def enviar_followup(to_number_wpp: str):
    time.sleep(45)

    to_number_wpp = normalize_to_wpp(to_number_wpp)
    if to_number_wpp not in lead_status:
        return

    lead = lead_status[to_number_wpp]

    if lead.get("answered"):
        return

    if lead.get("reminder_sent"):
        return

    try:
        msg = client.messages.create(
            from_=FROM_WPP,
            to=to_number_wpp,
            content_sid="HX1c8acc6fb0b98f806baf1d20c8ee9d54"
        )
        lead["reminder_sent"] = True
        salvar_log(
            number_wpp=to_number_wpp,
            body="(follow-up) lembrete automático enviado",
            stage=lead.get("stage", "start"),
            direction="system",
            message_sid=getattr(msg, "sid", ""),
            template_sid="HX1c8acc6fb0b98f806baf1d20c8ee9d54"
        )
        print("[INFO] Lembrete enviado para", to_number_wpp)
    except Exception as e:
        print("[ERRO] Falha ao enviar follow-up:", e)

# -------------------------------------------------------------
#  DETECTAR SIM / NÃO
# -------------------------------------------------------------
def respondeu_sim(body):
    body = safe_str(body).lower()
    positivas = [
        "s", "sim", "sim!", "sim?", "quero", "vamos",
        "ok", "pode", "pode mandar", "segue", "manda"
    ]
    return body in positivas or any(body.startswith(p) for p in positivas)

def respondeu_nao(body):
    body = safe_str(body).lower()
    negativas = [
        "n", "nao", "não", "não quero", "nao quero",
        "n quero", "não obrigada", "nao obrigado"
    ]
    return body in negativas or body.startswith("n")

# -------------------------------------------------------------
#  ROTA: HOME / FORM
# -------------------------------------------------------------
@app.route("/")
def home():
    return render_template("base.html", current_year=datetime.now().year)

@app.route("/form")
def form():
    return render_template("form.html")

# -------------------------------------------------------------
#  ROTA: LEADS (SHEETS)
# -------------------------------------------------------------
@app.route("/leads")
def leads_page():
    """
    Lista de leads vem da aba Página1 (Google Sheets).
    Observação: o Sheets pode retornar Telefone como int -> usamos safe_str + normalize_to_wpp.
    """
    try:
        ws = abrir_planilha()
        rows = ws.get_all_records()  # list[dict]
    except Exception as e:
        print("[ERRO AO LER LEADS DO SHEETS]", e)
        rows = []

    leads = {}
    for r in rows:
        tel_raw = r.get("TELEFONE") or r.get("Telefone") or r.get("telefone") or r.get("Telefone ") or ""
        telefone_wpp = normalize_to_wpp(tel_raw)
        if not telefone_wpp:
            continue

        stage = safe_str(r.get("STAGE") or r.get("Stage") or r.get("stage") or "start").lower() or "start"

        leads[telefone_wpp] = {"stage": stage}

    return render_template("leads.html", leads=leads)

# -------------------------------------------------------------
#  ROTA: LISTA DE CONVERSAS (SHEETS Página1)
# -------------------------------------------------------------
@app.route("/conversas")
def listar_conversas():
    try:
        ws = abrir_planilha()
        rows = ws.get_all_records()
    except Exception as e:
        print("[ERRO AO LER CONVERSAS DO SHEETS]", e)
        rows = []

    conversas = {}
    for r in rows:
        tel_raw = r.get("TELEFONE") or r.get("Telefone") or r.get("telefone") or ""
        telefone_wpp = normalize_to_wpp(tel_raw)
        if not telefone_wpp:
            continue

        stage = safe_str(r.get("STAGE") or r.get("Stage") or r.get("stage") or "start").lower()
        updated_at = safe_str(r.get("UPDATED_AT") or r.get("Updated_At") or r.get("updated_at") or r.get("LAST_OUTBOUND_AT") or "")

        conversas[telefone_wpp] = {"stage": stage or "start", "last_time": updated_at}

    return render_template("conversas_lista.html", leads=conversas)

# -------------------------------------------------------------
#  ROTA: CONVERSA INDIVIDUAL (SHEETS LOGS)
# -------------------------------------------------------------
@app.route("/conversas/<numero>")
def conversa_individual(numero):
    numero = normalize_to_wpp(numero)

    mensagens = []
    try:
        ensure_logs_worksheet()
        ws_logs = abrir_aba(LOGS_SHEET_NAME)
        logs = ws_logs.get_all_records()
    except Exception as e:
        print("[ERRO AO LER LOGS DO SHEETS]", e)
        logs = []

    for log in logs:
        telefone = normalize_to_wpp(log.get("TELEFONE") or log.get("Telefone") or "")
        if telefone != numero:
            continue

        ts = safe_str(log.get("TIMESTAMP") or "")
        time_str = ts if ts else datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        mensagens.append({
            "lead": telefone,
            "direction": safe_str(log.get("DIRECTION") or ""),
            "body": safe_str(log.get("BODY") or ""),
            "stage": safe_str(log.get("STAGE") or ""),
            "time": time_str,
            "timestamp": 0
        })

    return render_template("conversa.html", numero=numero, mensagens=mensagens)

# -------------------------------------------------------------
#  ROTA: ENVIAR (manual)
# -------------------------------------------------------------
@app.route("/enviar", methods=["POST"])
def enviar():
    nome = safe_str(request.form.get("nome", ""))
    telefone = safe_str(request.form.get("telefone", ""))

    wpp = normalize_to_wpp(telefone)
    if not wpp:
        return jsonify({"status": "erro", "erro": "Telefone inválido"}), 400

    vars_json = json.dumps({"nome": nome})
    template_sid = "HX3a3278be375c5f6368dc282229dfdd89"

    try:
        msg = client.messages.create(
            from_=FROM_WPP,
            to=wpp,
            content_sid=template_sid,
            content_variables=vars_json
        )

        # garante linha no Sheets + stage
        try:
            ws = abrir_planilha()
            row_idx, headers_l, _ = get_or_create_lead_row(ws, wpp, nome_padrao=nome or "profissional")
            update_lead_fields(ws, row_idx, headers_l, stage="start")
        except Exception as e:
            print("[WARN] Falha ao criar/atualizar lead no Sheets (manual):", e)

        lead_status[wpp] = {
            "timestamp": time.time(),
            "answered": False,
            "reminder_sent": False,
            "stage": "start",
            "nome": nome
        }

        # log outbound + metadados
        salvar_log(
            number_wpp=wpp,
            body="(start) template enviado",
            stage="start",
            direction="outbound",
            message_sid=getattr(msg, "sid", ""),
            template_sid=template_sid
        )

        threading.Thread(target=enviar_followup, args=(wpp,), daemon=True).start()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "erro", "erro": str(e)}), 500

# -------------------------------------------------------------
#  ROTA: WEBHOOK WhatsApp (Twilio)
# -------------------------------------------------------------
@app.route("/webhook-wpp", methods=["POST"])
def webhook():
    message_sid = safe_str(request.form.get("MessageSid", ""))

    if is_duplicate_message(message_sid):
        print(f"[DUPLICADO IGNORADO] MessageSid={message_sid}")
        return "ok", 200

    raw_body = safe_str(request.form.get("Body", ""))
    body_lower = raw_body.lower()

    from_number_raw = safe_str(request.form.get("From", ""))
    print("\nRAW NUMBER:", from_number_raw)

    from_number = normalize_to_wpp(from_number_raw)
    print("NORMALIZADO:", from_number)

    if not from_number:
        return "ok", 200

    # garante lead local
    if from_number not in lead_status:
        print("[INFO] Lead novo detectado via webhook")
        lead_status[from_number] = {
            "timestamp": time.time(),
            "answered": True,
            "reminder_sent": False,
            "stage": "start",
            "nome": ""
        }

    lead = lead_status[from_number]
    lead["answered"] = True
    if not lead.get("nome"):
        lead["nome"] = "profissional"

    # garante lead no Sheets
    try:
        ws = abrir_planilha()
        row_idx, headers_l, _ = get_or_create_lead_row(ws, from_number, nome_padrao=lead["nome"])
        # mantém stage atual no Sheets, se ainda não tiver
        update_lead_fields(ws, row_idx, headers_l, stage=lead.get("stage", "start"))
    except Exception as e:
        print("[WARN] Falha ao garantir lead no Sheets (webhook):", e)

    # salva inbound (stage atual)
    salvar_log(
        number_wpp=from_number,
        body=raw_body,
        stage=lead.get("stage", "start"),
        direction="inbound",
        message_sid=message_sid
    )

    # -------------------------------------------------------------
    # ETAPA 1 — start
    # -------------------------------------------------------------
    if lead["stage"] == "start":
        if respondeu_sim(body_lower):
            lead["stage"] = "nutricao"

            # outbound: fala + template
            salvar_log(
                number_wpp=from_number,
                body="Deixa eu te contar algo que quase ninguém percebe:",
                stage="nutricao",
                direction="outbound"
            )
            try:
                template_sid = "HX056f4623440f90a7d063f35c11e51b21"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(nutricao) template enviado", stage="nutricao",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template nutricao:", e)

            return "ok", 200

        if respondeu_nao(body_lower):
            lead["stage"] = "busca"
            salvar_log(
                number_wpp=from_number,
                body="Sem problemas! Se um dia quiser aprender profissionalmente, é só me chamar 💖 Quer mesmo assim conhecer como funciona o método Glam?",
                stage="busca",
                direction="outbound"
            )
            try:
                template_sid = "HX4d904d8b40ca29f56b466b5bf29b27b4"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(busca) template enviado", stage="busca",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template busca:", e)

            return "ok", 200

        return "ok", 200

    # -------------------------------------------------------------
    # ETAPA 2 — nutricao
    # -------------------------------------------------------------
    if lead["stage"] == "nutricao":
        if respondeu_sim(body_lower):
            lead["stage"] = "case"
            salvar_log(number_wpp=from_number, body="CASE REAL — A Virada de Chave Glam", stage="case", direction="outbound")
            try:
                template_sid = "HX7dd20c1f849fbfef0e86969e3bb830ed"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(case) template enviado", stage="case",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template case:", e)
            return "ok", 200

        if respondeu_nao(body_lower):
            lead["stage"] = "busca"
            salvar_log(number_wpp=from_number, body="Sem problemas! Se um dia quiser aprender profissionalmente, é só me chamar 💖 Quer mesmo assim conhecer como funciona o método Glam?",
                      stage="busca", direction="outbound")
            try:
                template_sid = "HX4d904d8b40ca29f56b466b5bf29b27b4"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(busca) template enviado", stage="busca",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template busca:", e)
            return "ok", 200

        return "ok", 200

    # -------------------------------------------------------------
    # ETAPA 3 — case
    # -------------------------------------------------------------
    if lead["stage"] == "case":
        if respondeu_sim(body_lower):
            lead["stage"] = "projecao"
            salvar_log(number_wpp=from_number, body="Deixa eu te revelar um ponto que, quando as profissionais entendem, a conversa muda de tom.",
                      stage="projecao", direction="outbound")
            try:
                template_sid = "HX9c35981fd182b8bafb7ba86f82f787c9"
                vars_json = json.dumps({"nome": lead.get("nome", "profissional")})
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid, content_variables=vars_json)
                salvar_log(number_wpp=from_number, body="(projecao) template enviado", stage="projecao",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template projecao:", e)
            return "ok", 200

        if respondeu_nao(body_lower):
            lead["stage"] = "busca"
            salvar_log(number_wpp=from_number, body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                      stage="busca", direction="outbound")
            try:
                template_sid = "HX4d904d8b40ca29f56b466b5bf29b27b4"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(busca) template enviado", stage="busca",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template busca:", e)
            return "ok", 200

        return "ok", 200

    # -------------------------------------------------------------
    # ETAPA — busca (recuperação)
    # -------------------------------------------------------------
    if lead["stage"] == "busca":
        if respondeu_sim(body_lower):
            lead["stage"] = "projecao"
            salvar_log(number_wpp=from_number, body="Retorno", stage="projecao", direction="outbound")
            try:
                template_sid = "HX056f4623440f90a7d063f35c11e51b21"
                vars_json = json.dumps({"nome": lead.get("nome", "profissional")})
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid, content_variables=vars_json)
                salvar_log(number_wpp=from_number, body="(projecao) template enviado", stage="projecao",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template projecao:", e)
            return "ok", 200

        return "ok", 200

    # -------------------------------------------------------------
    # ETAPA 4 — projecao
    # -------------------------------------------------------------
    if lead["stage"] == "projecao":
        if respondeu_sim(body_lower):
            lead["stage"] = "formacao_glam"
            salvar_log(number_wpp=from_number, body="Módulos", stage="formacao_glam", direction="outbound")
            try:
                template_sid = "HX5cf4af187864c97a446d5cbc1572ccca"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(formacao_glam) template enviado", stage="formacao_glam",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template formacao_glam:", e)
            return "ok", 200

        if respondeu_nao(body_lower):
            lead["stage"] = "end"
            salvar_log(number_wpp=from_number, body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                      stage="end", direction="outbound")
            try:
                template_sid = "HX4d904d8b40ca29f56b466b5bf29b27b4"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(end) template enviado", stage="end",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template end:", e)
            return "ok", 200

        return "ok", 200

    # -------------------------------------------------------------
    # ETAPA 5 — formacao_glam
    # -------------------------------------------------------------
    if lead["stage"] == "formacao_glam":
        if respondeu_sim(body_lower):
            lead["stage"] = "checkout"
            salvar_log(number_wpp=from_number, body="Link pagamento", stage="checkout", direction="outbound")
            try:
                template_sid = "HX8baef274f434c675cd1e1301dc8b4e4c"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(checkout) template enviado", stage="checkout",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template checkout:", e)
            return "ok", 200

        if respondeu_nao(body_lower):
            lead["stage"] = "end"
            salvar_log(number_wpp=from_number, body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                      stage="end", direction="outbound")
            try:
                template_sid = "HX4d904d8b40ca29f56b466b5bf29b27b4"
                msg = client.messages.create(from_=FROM_WPP, to=from_number, content_sid=template_sid)
                salvar_log(number_wpp=from_number, body="(end) template enviado", stage="end",
                          direction="system", message_sid=getattr(msg, "sid", ""), template_sid=template_sid)
            except Exception as e:
                print("[ERRO] envio template end:", e)
            return "ok", 200

        return "ok", 200

    return "ok", 200

# -------------------------------------------------------------
#  LOGS (aba LOGS)
# -------------------------------------------------------------
@app.route("/logs")
def visualizar_logs():
    try:
        ensure_logs_worksheet()
        ws_logs = abrir_aba(LOGS_SHEET_NAME)
        logs_rows = ws_logs.get_all_records()
    except Exception as e:
        print("[ERRO AO LER LOGS DO SHEETS]", e)
        logs_rows = []

    logs = []
    for r in logs_rows:
        logs.append({
            "lead": normalize_to_wpp(r.get("TELEFONE") or ""),
            "body": safe_str(r.get("BODY") or ""),
            "stage": safe_str(r.get("STAGE") or ""),
            "direction": safe_str(r.get("DIRECTION") or ""),
            "time": safe_str(r.get("TIMESTAMP") or "")
        })

    logs.reverse()
    return render_template("logs.html", logs=logs)

# -------------------------------------------------------------
#  DASHBOARD (Página1)
# -------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    try:
        ws = abrir_planilha()
        rows = ws.get_all_records()
    except Exception as e:
        print("[ERRO AO LER DASHBOARD DO SHEETS]", e)
        rows = []

    agora = datetime.now()
    hoje = agora.date()
    mes_atual = agora.month
    ano_atual = agora.year

    total = 0
    leads_dia = 0
    leads_mes = 0
    etapas_contagem = {}

    for r in rows:
        telefone_wpp = normalize_to_wpp(r.get("TELEFONE") or r.get("Telefone") or "")
        if not telefone_wpp:
            continue

        total += 1

        stage = safe_str(r.get("STAGE") or "start").lower() or "start"
        etapas_contagem[stage] = etapas_contagem.get(stage, 0) + 1

        dt_str = safe_str(r.get("UPDATED_AT") or r.get("LAST_OUTBOUND_AT") or "")
        dt = None
        if dt_str:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    break
                except Exception:
                    continue

        if dt:
            if dt.date() == hoje:
                leads_dia += 1
            if dt.year == ano_atual and dt.month == mes_atual:
                leads_mes += 1

    checkout = etapas_contagem.get("checkout_enviado", 0)
    comprou = etapas_contagem.get("comprou", 0)

    conversao = {"checkout_enviado": checkout, "comprou": comprou}

    metrics = {
        "total": total,
        "leads_dia": leads_dia,
        "leads_mes": leads_mes,
        "etapas_nomes": list(etapas_contagem.keys()),
        "etapas_valores": list(etapas_contagem.values())
    }

    return render_template("dashboard.html", metrics=metrics, conversao=conversao)

# -------------------------------------------------------------
#  DELETAR LEAD
# -------------------------------------------------------------
@app.route("/delete-lead/<numero>", methods=["POST"])
def delete_lead(numero):
    numero = normalize_to_wpp(numero)
    try:
        delete_lead_and_logs(numero)
    except Exception as e:
        print("[ERRO AO EXCLUIR NO SHEETS]", e)

    return redirect(url_for("leads_page", deleted="ok"))

# -------------------------------------------------------------
#  MARCAR COMO COMPROU
# -------------------------------------------------------------
@app.route("/marcar-comprou/<numero>", methods=["POST"])
def marcar_comprou(numero):
    numero = normalize_to_wpp(numero)
    try:
        ws = abrir_planilha()
        row_idx, headers_l, _ = get_or_create_lead_row(ws, numero)
        update_lead_fields(ws, row_idx, headers_l, stage="comprou")
        salvar_log(number_wpp=numero, body="Lead marcado como COMPROU manualmente", stage="comprou", direction="system")
    except Exception as e:
        print("[ERRO AO MARCAR COMPROU NO SHEETS]", e)

    return redirect(url_for("leads_page", comprado="ok"))

# -------------------------------------------------------------
#  CLICK CHECKOUT (exemplo)
# -------------------------------------------------------------
@app.route("/click-checkout")
def click_checkout():
    tel = request.args.get("tel", "")
    tel_wpp = normalize_to_wpp(tel)

    # registra no Sheets/log (independente da memória local)
    if tel_wpp:
        salvar_log(number_wpp=tel_wpp, body="Lead clicou no botão do checkout", stage="checkout_visit", direction="system")
        # opcional: atualiza stage no Sheets
        try:
            ws = abrir_planilha()
            row_idx, headers_l, _ = get_or_create_lead_row(ws, tel_wpp)
            update_lead_fields(ws, row_idx, headers_l, stage="checkout_visit")
        except Exception as e:
            print("[WARN] Falha ao atualizar stage checkout_visit:", e)

    return redirect("https://pay.hotmart.com/L102207547C")
