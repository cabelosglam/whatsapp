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


# -------------------------------------------------------------
#  CARREGAR VARIÁVEIS DE AMBIENTE (.env)
# -------------------------------------------------------------
load_dotenv()

# -------------------------------------------------------------
#  GOOGLE SHEETS como BANCO (Página1 + LOGS)
# -------------------------------------------------------------
from google_sheets import (
    abrir_planilha,
    append_log_row,
    get_or_create_lead_row,
    update_lead_fields,
    delete_lead_and_logs,
    get_records,
    LOGS_SHEET_NAME,
    SHEET_NAME,
)


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

def salvar_log(number, body, stage, direction, message_sid="", template_sid=""):
    """Salva log de forma PERSISTENTE no Google Sheets (aba LOGS) e atualiza a linha do lead na Página1.

    number deve ser no formato 'whatsapp:+55...'
    """
    try:
        # 1) append na aba LOGS
        append_log_row(
            telefone_wpp=number,
            direction=direction,
            stage=stage,
            body=body,
            message_sid=message_sid,
            template_sid=template_sid
        )

        # 2) update do lead na Página1 (stage + últimos campos)
        ws = abrir_planilha()  # abre a aba SHEET_NAME
        row_idx, headers_l, _ = get_or_create_lead_row(ws, number)

        fields = {"stage": stage}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if direction == "inbound":
            fields.update({
                "last_inbound": body,
                "last_inbound_at": now_str
            })
        else:
            fields.update({
                "last_outbound": body,
                "last_outbound_at": now_str
            })

        if template_sid:
            fields["last_template_sid"] = template_sid
        if message_sid:
            fields["last_message_sid"] = message_sid

        update_lead_fields(ws, row_idx, headers_l, **fields)

    except Exception as e:
        print("[ERRO AO SALVAR LOG NO SHEETS]", e)
        # fallback opcional: não quebra o fluxo se Sheets falhar
        try:
            entry = {
                "timestamp": time.time(),
                "lead": number,
                "direction": direction,
                "body": body,
                "stage": stage
            }
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
        except Exception as ee:
            print("[FALLBACK LOGS.JSON FALHOU]", ee)



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
def leads_page():
    """Lista de leads vem da aba Página1 (Google Sheets)."""
    try:
        ws = abrir_planilha()
        rows = ws.get_all_records()  # list[dict]
    except Exception as e:
        print("[ERRO AO LER LEADS DO SHEETS]", e)
        rows = []

    leads = {}

    for r in rows:
        # tenta diferentes nomes de coluna (case-insensitive no Sheets vira exatamente como está no header)
        telefone = (r.get("TELEFONE") or r.get("Telefone") or r.get("telefone") or "").strip()
        if not telefone:
            continue

        stage = (r.get("STAGE") or r.get("Stage") or r.get("stage") or "").strip() or "start"
        # normaliza
        stage = stage.lower()

        leads[telefone] = {
            "stage": stage
        }

    return render_template("leads.html", leads=leads)





@app.route("/conversas")
def listar_conversas():
    """Lista conversas a partir da Página1 (lead -> stage)."""
    try:
        ws = abrir_planilha()
        rows = ws.get_all_records()
    except Exception as e:
        print("[ERRO AO LER CONVERSAS DO SHEETS]", e)
        rows = []

    conversas = {}
    for r in rows:
        telefone = (r.get("TELEFONE") or r.get("Telefone") or r.get("telefone") or "").strip()
        if not telefone:
            continue
        stage = (r.get("STAGE") or r.get("Stage") or r.get("stage") or "start").strip().lower()
        updated_at = (r.get("UPDATED_AT") or r.get("Updated_At") or r.get("updated_at") or "").strip()

        conversas[telefone] = {
            "stage": stage,
            "last_time": updated_at
        }

    return render_template("conversas_lista.html", leads=conversas)





@app.route("/conversas/<numero>")
def conversa_individual(numero):
    """Conversa individual vem da aba LOGS."""
    mensagens = []
    try:
        ensure_logs_worksheet()
        ws_logs = abrir_aba(LOGS_SHEET_NAME)
        logs = ws_logs.get_all_records()
    except Exception as e:
        print("[ERRO AO LER LOGS DO SHEETS]", e)
        logs = []

    for log in logs:
        telefone = (log.get("TELEFONE") or log.get("Telefone") or "").strip()
        if telefone != numero:
            continue

        ts = (log.get("TIMESTAMP") or "").strip()
        # TIMESTAMP está como string, então já geramos um 'time' amigável
        time_str = ts if ts else datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        mensagens.append({
            "lead": telefone,
            "direction": (log.get("DIRECTION") or "").strip(),
            "body": (log.get("BODY") or "").strip(),
            "stage": (log.get("STAGE") or "").strip(),
            "time": time_str,
            "timestamp": 0
        })

    return render_template("conversa.html", numero=numero, mensagens=mensagens)






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



# -------------------------------------------------------------
# ROTA: Webhook do WhatsApp (Twilio)
# -------------------------------------------------------------
@app.route("/webhook-wpp", methods=["POST"])
def webhook():
    message_sid = request.form.get("MessageSid", "")

    if is_duplicate_message(message_sid):
        print(f"[DUPLICADO IGNORADO] MessageSid={message_sid}")
        return "ok", 200

    raw_body = request.form.get("Body", "").strip()
    body = raw_body.lower()

    from_number_raw = request.form.get("From", "").strip()
    print("\nRAW NUMBER:", from_number_raw)

    # Normalizar
    if from_number_raw.startswith("whatsapp:"):
        from_number = from_number_raw
    else:
        clean = from_number_raw.replace("+", "")
        from_number = f"whatsapp:+{clean}"

    print("NORMALIZADO:", from_number)

    # Criar lead se não existir (ANTES do salvar_log inbound)
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

    if lead.get("nome", "") == "":
        lead["nome"] = "profissional"

    nome = lead["nome"]

    # Agora sim salva log inbound com stage correto
    salvar_log(
        number=from_number,
        body=raw_body,  # salva o texto original
        stage=lead.get("stage", "desconhecido"),
        direction="inbound"
    )
    # -------------------------------------------------------------
    # ETAPA 1 — Pergunta inicial
    # -------------------------------------------------------------
    if lead["stage"] == "start":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="Deixa eu te contar algo que quase ninguém percebe:",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "nutricao"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX056f4623440f90a7d063f35c11e51b21"
            )
            
            return "ok", 200

        if respondeu_nao(body):
            salvar_log(
                number=from_number,
                body="Sem problemas! Se um dia quiser aprender profissionalmente, é só me chamar 💖Quer mesmo assim conhecer como funciona o método Glam?",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "busca"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4"
            )
            
            return "ok", 200

        return "ok", 200



    # -------------------------------------------------------------
    # ETAPA 2 — Nutrição
    # -------------------------------------------------------------
    if lead["stage"] == "nutricao":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="CASE REAL — A Virada de Chave Glam",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "case"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX7dd20c1f849fbfef0e86969e3bb830ed"
            )
        
            return "ok", 200

        if respondeu_nao(body):
            salvar_log(
                number=from_number,
                body="Sem problemas! Se um dia quiser aprender profissionalmente, é só me chamar 💖Quer mesmo assim conhecer como funciona o método Glam?",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "busca"


            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4"
            )
            return "ok", 200

        return "ok", 200



    # -------------------------------------------------------------
    # ETAPA 3 — Case de Sucesso
    # -------------------------------------------------------------
    if lead["stage"] == "case":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="Deixa eu te revelar um ponto que, quando as profissionais entendem, a conversa muda de tom.",
                stage=lead["stage"],
                direction="outbound"
            )


            vars_json = json.dumps({"nome": nome})
            
            lead["stage"] = "projecao"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX9c35981fd182b8bafb7ba86f82f787c9",
                content_variables=vars_json
            )

            return "ok", 200

        if respondeu_nao(body):
            salvar_log(
                number=from_number,
                body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "busca"


            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4"
            )
            return "ok", 200

        return "ok", 200



    # -------------------------------------------------------------
    # ETAPA — RECUPERAÇÃO (OPÇÃO B)
    # Lead disse "não" mas depois mandou "sim"
    # -------------------------------------------------------------
    if lead["stage"] == "busca":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="Retorno",
                stage=lead["stage"],
                direction="outbound"
            )


            print("[INFO] Lead voltou após dizer NÃO — retornando para CASE")

            vars_json = json.dumps({"nome": nome})

            lead["stage"] = "projecao"


            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX056f4623440f90a7d063f35c11e51b21",
                content_variables=vars_json
            )
            return "ok", 200

        return "ok", 200



    # -------------------------------------------------------------
    # ETAPA 4 — Projeção
    # -------------------------------------------------------------
    if lead["stage"] == "projecao":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="Módulos",
                stage=lead["stage"],
                direction="outbound"
            )
            
            lead["stage"] = "formacao_glam"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX5cf4af187864c97a446d5cbc1572ccca"
            )
            return "ok", 200

        if respondeu_nao(body):
            salvar_log(
                number=from_number,
                body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "end"


            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4"
            )
            return "ok", 200

        return "ok", 200



    # -------------------------------------------------------------
    # ETAPA 5 — Formação GLAM
    # -------------------------------------------------------------
    if lead["stage"] == "formacao_glam":

        if respondeu_sim(body):
            salvar_log(
                number=from_number,
                body="Link pagamento",
                stage=lead["stage"],
                direction="outbound"
            )
            lead["stage"] = "checkout"

            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX8baef274f434c675cd1e1301dc8b4e4c"
            )
            return "ok", 200

        if respondeu_nao(body):
            salvar_log(
                number=from_number,
                body="quer ver uma coisa que costuma abrir os olhos das profissionais?",
                stage=lead["stage"],
                direction="outbound"
            )

            lead["stage"] = "end"


            client.messages.create(
                from_=FROM_WPP,
                to=from_number,
                content_sid="HX4d904d8b40ca29f56b466b5bf29b27b4"
            )
            return "ok", 200

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
    """Exibe logs a partir da aba LOGS (Google Sheets)."""
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
            "lead": (r.get("TELEFONE") or "").strip(),
            "body": (r.get("BODY") or "").strip(),
            "stage": (r.get("STAGE") or "").strip(),
            "direction": (r.get("DIRECTION") or "").strip(),
            "time": (r.get("TIMESTAMP") or "").strip()
        })

    # mais recentes primeiro
    logs.reverse()

    return render_template("logs.html", logs=logs)




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
        telefone = (r.get("TELEFONE") or r.get("Telefone") or "").strip()
        if not telefone:
            continue
        total += 1

        stage = (r.get("STAGE") or "start").strip().lower()
        etapas_contagem[stage] = etapas_contagem.get(stage, 0) + 1

        # usa UPDATED_AT se existir; senão tenta LAST_OUTBOUND_AT
        dt_str = (r.get("UPDATED_AT") or r.get("LAST_OUTBOUND_AT") or r.get("Last_Outbound_At") or "").strip()
        dt = None
        if dt_str:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    break
                except:
                    continue

        if dt:
            if dt.date() == hoje:
                leads_dia += 1
            if dt.year == ano_atual and dt.month == mes_atual:
                leads_mes += 1

    # conversão simples: quantos em "checkout_enviado" e "comprou"
    checkout = etapas_contagem.get("checkout_enviado", 0)
    comprou = etapas_contagem.get("comprou", 0)

    conversao = {
        "checkout_enviado": checkout,
        "comprou": comprou
    }

    metrics = {
        "total": total,
        "leads_dia": leads_dia,
        "leads_mes": leads_mes,
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
    """Página antiga de lead: agora usa LOGS do Sheets."""
    try:
        ensure_logs_worksheet()
        ws_logs = abrir_aba(LOGS_SHEET_NAME)
        logs_rows = ws_logs.get_all_records()
    except Exception as e:
        print("[ERRO AO LER LOGS NO LEAD_VIEW]", e)
        logs_rows = []

    conversa = []
    for r in logs_rows:
        tel = (r.get("TELEFONE") or "").strip()
        if tel != id:
            continue
        conversa.append({
            "lead": tel,
            "body": (r.get("BODY") or "").strip(),
            "stage": (r.get("STAGE") or "").strip(),
            "direction": (r.get("DIRECTION") or "").strip(),
            "time": (r.get("TIMESTAMP") or "").strip(),
            "timestamp": 0
        })

    return render_template("lead.html", lead=id, logs=conversa)



from flask import redirect, url_for

@app.route("/delete-lead/<numero>", methods=["POST"])
def delete_lead(numero):
    try:
        delete_lead_and_logs(numero)
    except Exception as e:
        print("[ERRO AO EXCLUIR NO SHEETS]", e)

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
    try:
        # atualiza na Página1
        ws = abrir_planilha()
        row_idx, headers_l, _ = get_or_create_lead_row(ws, numero)
        update_lead_fields(ws, row_idx, headers_l, stage="comprou")

        # loga na LOGS
        salvar_log(
            number=numero,
            body="Lead marcado como COMPROU manualmente",
            stage="comprou",
            direction="system"
        )
    except Exception as e:
        print("[ERRO AO MARCAR COMPROU NO SHEETS]", e)

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