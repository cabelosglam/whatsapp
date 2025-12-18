from flask import Flask, render_template, request, jsonify, redirect
from twilio.rest import Client
from dotenv import load_dotenv
import os, json, time, threading
# DESATIVE PARA O HEROKU
# from google_sheets import monitorar_novos_leads
import threading
import json
from datetime import datetime
import time
from google_sheets import abrir_planilha, get_or_create_lead, update_fields, append_historico, listar_leads_para_painel


# -------------------------------------------------------------
#  CARREGAR VARIÁVEIS DE AMBIENTE (.env)
# -------------------------------------------------------------
load_dotenv()

app = Flask(__name__)

ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
FROM_WPP = os.getenv("FROM_WPP")  # Exemplo: whatsapp:+14155238886

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# -------------------------------------------------------------
# MEMÓRIA LOCAL PARA OS LEADS
# -------------------------------------------------------------
lead_status = {}

def processar_novo_lead_sheet(nome, telefone, email):
    """
    É chamado automaticamente toda vez que alguém novo aparece na planilha.
    Aqui reaproveitamos o mesmo fluxo do formulário!
    """
    print(f"[PROCESSANDO NOVO LEAD] {nome} | {telefone}")

    # Simula o envio via formulário
    with app.test_request_context(method="POST", data={"nome": nome, "telefone": telefone}):
        enviar()

# -------------------------------------------------------------
# FUNÇÃO: Normalizar Telefone
# -------------------------------------------------------------
def normalize_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))

    if len(digits) in (10, 11):
        return "55" + digits
    
    if len(digits) in (12, 13):
        return digits
    
    return ""

# -------------------------------------------------------------
# FUNÇÃO: anti-duplicidade
# -------------------------------------------------------------

PROCESSED_SIDS_FILE = "processed_sids.json"

def load_processed_sids():
    if os.path.exists(PROCESSED_SIDS_FILE):
        try:
            with open(PROCESSED_SIDS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_processed_sids(sids_set):
    with open(PROCESSED_SIDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sids_set), f, ensure_ascii=False, indent=2)

processed_sids = load_processed_sids()

def is_duplicate_message(message_sid: str) -> bool:
    if not message_sid:
        return False
    if message_sid in processed_sids:
        return True
    processed_sids.add(message_sid)

    # (opcional) limita o arquivo para não crescer infinito
    if len(processed_sids) > 5000:
        # mantém só os últimos 2000
        processed_sids_list = list(processed_sids)[-2000:]
        processed_sids.clear()
        processed_sids.update(processed_sids_list)

    save_processed_sids(processed_sids)
    return False

# -------------------------------------------------------------
# FUNÇÃO: SALVAR MENSAGENS DE LOG JSON
# -------------------------------------------------------------

def salvar_log(number, body, stage, direction):
    entry = {
        "timestamp": time.time(),
        "lead": number,
        "direction": direction,
        "body": body,
        "stage": stage
    }

    try:
        logs = []
        if os.path.exists("logs.json") and os.path.getsize("logs.json") > 0:
            try:
                with open("logs.json", "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except:
                logs = []

        logs.append(entry)

        with open("logs.json", "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)

    except Exception as e:
        print("[ERRO AO SALVAR LOG]", e)


# -------------------------------------------------------------
# FUNÇÃO: Enviar lembrete se o lead não responder
# -------------------------------------------------------------
def enviar_followup(from_number: str):
    time.sleep(45)

    if from_number not in lead_status:
        return

    lead = lead_status[from_number]

    if lead["answered"]:
        return

    if lead["reminder_sent"]:
        return

    client.messages.create(
        from_=FROM_WPP,
        to=from_number,
        content_sid="HX1c8acc6fb0b98f806baf1d20c8ee9d54"
    )

    lead["reminder_sent"] = True
    print("[INFO] Lembrete enviado para", from_number)



# -------------------------------------------------------------
# FUNÇÕES AUXILIARES: detectar SIM / NÃO
# -------------------------------------------------------------
def respondeu_sim(body):
    body = body.strip().lower()
    positivas = [
        "s", "sim", "sim!", "sim?", "quero", "vamos",
        "ok", "pode", "pode mandar", "segue", "manda"
    ]
    return body in positivas or any(body.startswith(p) for p in positivas)


def respondeu_nao(body):
    body = body.strip().lower()
    negativas = [
        "n", "nao", "não", "não quero", "nao quero",
        "n quero", "não obrigada", "nao obrigado"
    ]
    return body in negativas or body.startswith("n")



# -------------------------------------------------------------
# ROTA: Exibir formulário
# -------------------------------------------------------------
@app.route("/")
def home():
    from datetime import datetime
    return render_template("base.html", current_year=datetime.now().year)

@app.route("/form")
def form():
    return render_template("form.html")



@app.route("/leads")
def leads():
    leads_dict = listar_leads_para_painel()
    return render_template("leads.html", leads=leads_dict)



@app.route("/conversas")
def listar_conversas():

    # Carrega logs
    if not os.path.exists("logs.json"):
        return render_template("conversas_lista.html", leads={})

    try:
        with open("logs.json", "r", encoding="utf-8") as f:
            logs = json.load(f)
    except:
        logs = []

    conversas = {}

    # Montar lista baseada nos logs
    for log in logs:
        numero = log.get("lead")
        if not numero:
            continue

        if numero not in conversas:
            conversas[numero] = {
                "stage": log.get("stage", "desconhecido"),
                "last_time": log.get("timestamp"),
            }
        else:
            # Atualiza o stage e timestamp se for mais recente
            if log.get("timestamp") > conversas[numero]["last_time"]:
                conversas[numero]["stage"] = log.get("stage", "desconhecido")
                conversas[numero]["last_time"] = log.get("timestamp")

    return render_template("conversas_lista.html", leads=conversas)



@app.route("/conversas/<numero>")
def conversa_individual(numero):

    if not os.path.exists("logs.json"):
        return render_template("conversa.html", numero=numero, mensagens=[])

    try:
        with open("logs.json", "r", encoding="utf-8") as f:
            logs = json.load(f)
    except:
        logs = []

    conversas = []

    for log in logs:
        if log.get("lead") == numero:
            conversas.append(log)


    # ordenar por tempo
    conversas.sort(key=lambda x: x.get("timestamp", 0))

    # formata timestamps
    for msg in conversas:
        msg["time"] = datetime.fromtimestamp(msg["timestamp"]).strftime("%d/%m/%Y %H:%M:%S")

    return render_template("conversa.html", numero=numero, mensagens=conversas)




# -------------------------------------------------------------
# ROTA: Disparar primeira mensagem
# -------------------------------------------------------------
@app.route("/enviar", methods=["POST"])
def enviar():
    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()

    numero = normalize_phone(telefone)
    if numero == "":
        return jsonify({"status": "erro", "erro": "Telefone inválido"}), 400

    wpp = f"whatsapp:+{numero}"
    vars_json = json.dumps({"nome": nome})

    try:
        client.messages.create(
            from_=FROM_WPP,
            to=wpp,
            content_sid="HX3a3278be375c5f6368dc282229dfdd89",
            content_variables=vars_json
        )

        lead_status[wpp] = {
            "timestamp": time.time(),
            "answered": False,
            "reminder_sent": False,
            "stage": "start",
            "nome": nome
        }

        threading.Thread(
            target=enviar_followup,
            args=(wpp,),
            daemon=True
        ).start()

        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "erro", "erro": str(e)}), 500



@app.route("/click-checkout")
def click_checkout():
    tel = (request.args.get("tel") or "").strip()
    tel = normalizar_whatsapp_number(tel)

    ws = abrir_planilha()
    row_idx, headers_l, lead = get_or_create_lead(ws, tel, nome_padrao="profissional")

    update_fields(ws, row_idx, headers_l, checkout_clicked_at=now_str())
    append_historico(ws, row_idx, headers_l, "CHECKOUT CLICKED")

    # seu link Hotmart:
    return redirect("https://pay.hotmart.com/L102207547C", code=302)

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def normalizar_whatsapp_number(from_number_raw: str) -> str:
    from_number_raw = (from_number_raw or "").strip()
    if from_number_raw.startswith("whatsapp:"):
        return from_number_raw
    clean = from_number_raw.replace("+", "").strip()
    if clean.startswith("whatsapp:"):
        return clean
    return f"whatsapp:+{clean}"

def respondeu_sim(body: str) -> bool:
    b = (body or "").strip().lower()
    return b in ["sim", "s", "yes", "y", "claro", "ok", "quero", "quero sim", "ss"]

def respondeu_nao(body: str) -> bool:
    b = (body or "").strip().lower()
    return b in ["não", "nao", "n", "no", "não quero", "nao quero"]

def now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# -------------------------------------------------------------
# ROTA: Webhook do WhatsApp (Twilio)
# -------------------------------------------------------------
@app.route("/webhook-wpp", methods=["POST"])
def webhook():
    message_sid = (request.form.get("MessageSid") or "").strip()
    raw_body = (request.form.get("Body") or "").strip()
    body = raw_body.lower()

    from_number_raw = (request.form.get("From") or "").strip()
    from_number = normalizar_whatsapp_number(from_number_raw)

    print("\nRAW NUMBER:", from_number_raw)
    print("NORMALIZADO:", from_number)
    print("BODY:", raw_body)

    ws = abrir_planilha()
    row_idx, headers_l, lead = get_or_create_lead(ws, from_number, nome_padrao="profissional")

    # -------------------------
    # Idempotência inbound: se o mesmo MessageSid chegar de novo, ignora.
    # Usa sua coluna LAST_MESSAGE_SID (inbound).
    # -------------------------
    last_in_sid = (lead.get("last_message_sid") or "").strip()
    if message_sid and last_in_sid == message_sid:
        print("[DUPLICADO] mesmo MessageSid, ignorando.")
        return "ok", 200

    # stage vem do Sheets (verdade única)
    stage = (lead.get("stage") or "start").strip() or "start"
    nome = (lead.get("nome") or "profissional").strip() or "profissional"

    # Salva inbound no Sheets
    update_fields(
        ws, row_idx, headers_l,
        last_message_sid=message_sid,
        last_inbound=raw_body,
        updated_at=now_str()
    )
    append_historico(ws, row_idx, headers_l, f"INBOUND ({stage}): {raw_body}")

    # -------------------------------------------------------------
    # FUNÇÃO local para enviar template + registrar no Sheets
    # -------------------------------------------------------------
    def enviar_template(content_sid, next_stage=None, content_variables=None, outbound_text_log=None):
        # Atualiza stage antes de enviar (evita corrida)
        if next_stage:
            update_fields(ws, row_idx, headers_l, stage=next_stage, updated_at=now_str())

        # Envia
        kwargs = dict(from_=FROM_WPP, to=from_number, content_sid=content_sid)
        if content_variables:
            kwargs["content_variables"] = json.dumps(content_variables)

        msg = client.messages.create(**kwargs)

        # Log no Sheets
        update_fields(
            ws, row_idx, headers_l,
            last_template_sid=content_sid,
            last_outbound_at=now_str(),
            last_outbound=(outbound_text_log or f"TEMPLATE {content_sid}"),
            # se você quiser guardar o SID outbound, crie coluna LAST_OUTBOUND_SID
        )
        append_historico(ws, row_idx, headers_l, f"OUTBOUND: {outbound_text_log or content_sid}")

        return msg

    # -------------------------------------------------------------
    # STAGES
    # -------------------------------------------------------------
    if stage == "start":
        if respondeu_sim(body):
            enviar_template(
                content_sid="HX056f4623440f90a7d063f35c11e51b21",
                next_stage="nutricao",
                outbound_text_log="Nutrição 1"
            )
            return "ok", 200

        if respondeu_nao(body):
            enviar_template(
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4",
                next_stage="busca",
                outbound_text_log="Recuperação (disse não)"
            )
            return "ok", 200

        return "ok", 200

    if stage == "nutricao":
        if respondeu_sim(body):
            enviar_template(
                content_sid="HX7dd20c1f849fbfef0e86969e3bb830ed",
                next_stage="case",
                outbound_text_log="Case"
            )
            return "ok", 200

        if respondeu_nao(body):
            enviar_template(
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4",
                next_stage="busca",
                outbound_text_log="Recuperação (na nutrição)"
            )
            return "ok", 200

        return "ok", 200

    if stage == "case":
        if respondeu_sim(body):
            enviar_template(
                content_sid="HX9c35981fd182b8bafb7ba86f82f787c9",
                next_stage="projecao",
                content_variables={"nome": nome},
                outbound_text_log="Projeção"
            )
            return "ok", 200

        if respondeu_nao(body):
            enviar_template(
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4",
                next_stage="busca",
                outbound_text_log="Recuperação (no case)"
            )
            return "ok", 200

        return "ok", 200

    # Recuperação: lead disse não e depois voltou com sim
    if stage == "busca":
        if respondeu_sim(body):
            # escolha: voltar para NUTRIÇÃO (faz mais sentido do que pular)
            enviar_template(
                content_sid="HX056f4623440f90a7d063f35c11e51b21",
                next_stage="nutricao",
                outbound_text_log="Voltou (retomando nutrição)"
            )
            return "ok", 200
        return "ok", 200

    if stage == "projecao":
        if respondeu_sim(body):
            enviar_template(
                content_sid="HX5cf4af187864c97a446d5cbc1572ccca",
                next_stage="formacao_glam",
                outbound_text_log="Módulos"
            )
            return "ok", 200

        if respondeu_nao(body):
            enviar_template(
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4",
                next_stage="end",
                outbound_text_log="Encerrado (disse não na projeção)"
            )
            return "ok", 200

        return "ok", 200

    if stage == "formacao_glam":
        if respondeu_sim(body):
            enviar_template(
                content_sid="HX8baef274f434c675cd1e1301dc8b4e4c",
                next_stage="checkout",
                outbound_text_log="Checkout"
            )
            return "ok", 200

        if respondeu_nao(body):
            enviar_template(
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4",
                next_stage="end",
                outbound_text_log="Encerrado (disse não na formação)"
            )
            return "ok", 200

        return "ok", 200

    # Se já está em checkout/end, só registra e não fica repetindo
    return "ok", 200


def iniciar_fluxo_via_planilha(nome, telefone):
    """
    Simula a mesma lógica da rota /enviar,
    disparando automaticamente pelo Google Sheets.
    """
    numero = normalize_phone(telefone)
    if numero == "":
        print("[ERRO] Telefone inválido vindo do Google Sheets:", telefone)
        return
    
    wpp = f"whatsapp:+{numero}"
    vars_json = json.dumps({"nome": nome})

    try:
        client.messages.create(
            from_=FROM_WPP,
            to=wpp,
            content_sid="HXfb376726c199d4fc794977c6d62c4037",
            content_variables=vars_json
        )

        lead_status[wpp] = {
            "timestamp": time.time(),
            "answered": False,
            "reminder_sent": False,
            "stage": "start",
            "nome": nome
        }

        threading.Thread(
            target=enviar_followup,
            args=(wpp,),
            daemon=True
        ).start()

        print(f"[FLOW] Fluxo iniciado automaticamente para {nome} ({telefone})")

    except Exception as e:
        print("[ERRO AO ENVIAR MENSAGEM]", e)

@app.route("/logs")
def visualizar_logs():
    if not os.path.exists("logs.json"):
        logs = []
    else:
        logs = []
        if os.path.exists("logs.json") and os.path.getsize("logs.json") > 0:
            try:
                with open("logs.json", "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except json.JSONDecodeError:
                print("[ERRO] logs.json corrompido. Reinicializando.")
                logs = []


    for l in logs:
        l["time"] = datetime.fromtimestamp(l["timestamp"]).strftime("%d/%m/%Y %H:%M:%S")

    return render_template("logs.html", logs=logs[::-1])


@app.route("/dashboard")
def dashboard():
    # Carrega logs
    if not os.path.exists("logs.json"):
        logs = []
    else:
        with open("logs.json", "r", encoding="utf-8") as f:
            logs = json.load(f)

    agora = datetime.now()
    hoje = agora.date()
    mes_atual = agora.month
    ano_atual = agora.year

    leads_dia = set()
    leads_mes = set()
    leads_total = set()

    etapas_final = {}       # guarda a última etapa de cada lead
    etapas_contagem = {}    # conta quantos leads terminaram em cada etapa

    for log in logs:
        lead = log.get("lead")
        if not lead:
            continue

        etapa = log.get("stage", "desconhecido")
        timestamp = log.get("timestamp", 0)

        dt = datetime.fromtimestamp(timestamp)
        leads_total.add(lead)

        if dt.date() == hoje:
            leads_dia.add(lead)

        if dt.year == ano_atual and dt.month == mes_atual:
            leads_mes.add(lead)

        # registra última etapa do lead
        etapas_final[lead] = etapa

    # contabiliza as etapas
    for etapa in etapas_final.values():
        etapas_contagem[etapa] = etapas_contagem.get(etapa, 0) + 1

    # total de leads
    total = len(leads_total)

    def conv(etapa):
        return round((etapas_contagem.get(etapa, 0) / total * 100), 1) if total else 0

    conversao = {
        "para_start": conv("start"),
        "para_nutricao": conv("nutricao"),
        "para_case": conv("case"),
        "para_projecao": conv("projecao"),
        "para_checkout": conv("checkout"),
        "para_comprou": conv("comprou")    # <-- AGORA FUNCIONANDO
    }

    metrics = {
        "dia": len(leads_dia),
        "mes": len(leads_mes),
        "total": len(leads_total),
        "etapas": etapas_contagem,
        "etapas_nomes": list(etapas_contagem.keys()),
        "etapas_valores": list(etapas_contagem.values())
    }

    return render_template(
        "dashboard.html",
        metrics=metrics,
        conversao=conversao
    )


@app.template_filter('datetimeformat')
def datetimeformat(value):
    return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M")

@app.route("/lead/<id>")
def lead_view(id):
    if not os.path.exists("logs.json"):
        return "Sem logs ainda."

    with open("logs.json", "r", encoding="utf-8") as f:
        logs = json.load(f)

    conversa = [l for l in logs if l["lead"] == id]

    conversa_sorted = sorted(conversa, key=lambda x: x["timestamp"])

    return render_template("lead.html", lead=id, logs=conversa_sorted)

from flask import redirect, url_for

@app.route("/delete-lead/<numero>", methods=["POST"])
def delete_lead(numero):

    # 1 — Remover da memória
    if numero in lead_status:
        del lead_status[numero]

    # 2 — Remover do logs.json
    try:
        if os.path.exists("logs.json"):
            with open("logs.json", "r", encoding="utf-8") as f:
                logs = json.load(f)

            logs = [l for l in logs if l.get("lead") != numero]

            with open("logs.json", "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=4, ensure_ascii=False)
    except:
        pass

    # 3 — Redireciona PARA /leads com parâmetro de confirmação
    return redirect(url_for("leads_page", deleted="ok"))

@app.route("/click-checkout")
def click_checkout():
    telefone = request.args.get("tel")

    if telefone:
        telefone = normalize_phone(telefone)

    if telefone in lead_status:
        lead_status[telefone]["stage"] = "checkout_visit"

        salvar_log(
            number=telefone,
            body="Lead clicou no botão do checkout",
            stage="checkout_visit",
            direction="system"
        )

    return redirect("https://pay.hotmart.com/L102207547C")


@app.route("/marcar-comprou/<numero>", methods=["POST"])
def marcar_comprou(numero):

    # Atualiza lead_status em memória (opcional)
    if numero in lead_status:
        lead_status[numero]["stage"] = "comprou"
        lead_status[numero]["last_message"] = "Comprou manualmente"

    # Carrega logs
    if os.path.exists("logs.json"):
        try:
            with open("logs.json", "r", encoding="utf-8") as f:
                logs = json.load(f)
        except:
            logs = []
    else:
        logs = []

    # Adiciona novo registro
    logs.append({
        "timestamp": time.time(),
        "lead": numero,
        "direction": "system",
        "body": "Lead marcado como COMPROU manualmente",
        "stage": "comprou"
    })

    # Salva de volta
    with open("logs.json", "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=4, ensure_ascii=False)

    # Volta à página de leads com mensagem
    return redirect(url_for("leads_page", comprado="ok"))



# -------------------------------------------------------------
# INICIAR SERVIDOR
# -------------------------------------------------------------
#if __name__ == "__main__":
    # Iniciar monitoramento do Google Sheets em thread paralela
    # FEATURE DESATIVADA NO HEROKU
    # threading.Thread(
    #     target=monitorar_novos_leads,
    #     args=(processar_novo_lead_sheet,),
    #     daemon=True
    # ).start()

    #print("[INFO] Monitoramento Google Sheets iniciado.")
    #app.run(debug=True)     
