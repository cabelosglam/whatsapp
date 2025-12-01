from flask import Flask, render_template, request, jsonify
from twilio.rest import Client
from dotenv import load_dotenv
import os, json

load_dotenv()

app = Flask(__name__)

# Credenciais
ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
FROM_WPP = os.getenv("FROM_WPP")  # "whatsapp:+14155238886"

client = Client(ACCOUNT_SID, AUTH_TOKEN)


@app.route("/")
def index():
    return render_template("form.html")

def normalize_phone(phone):
    # Mantém somente números
    digits = ''.join(filter(str.isdigit, phone))

    # Se tiver somente 10 ou 11 dígitos, assumimos Brasil
    if len(digits) == 10:  # ex: 1199999999
        return "55" + digits
    if len(digits) == 11:  # ex: 11999999999
        return "55" + digits

    # Se já veio com 13 dígitos (55 + DDD + número)
    if len(digits) == 12 or len(digits) == 13:
        return digits

    # Número inválido → retorna vazio (para não quebrar)
    return ""
    
@app.route("/enviar", methods=["POST"])
def enviar():

    nome = request.form.get("nome")
    telefone = request.form.get("telefone")

    # Normaliza o número
    telefone_normalizado = normalize_phone(telefone)

    if telefone_normalizado == "":
        return jsonify({"status": "erro", "detalhes": "Telefone inválido"}), 400

    vars_json = json.dumps({
        "nome": nome
    })

    try:
        msg = client.messages.create(
            from_=FROM_WPP,
            to=f"whatsapp:+{telefone_normalizado}",
            content_sid="COLOQUE_SEU_CONTENT_SID_AQUI",
            content_variables=vars_json
        )

        return jsonify({"status": "ok", "sid": msg.sid})

    except Exception as e:
        return jsonify({"status": "erro", "detalhes": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
