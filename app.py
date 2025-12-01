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


@app.route("/enviar", methods=["POST"])
def enviar():

    nome = request.form.get("nome")
    telefone = request.form.get("telefone")

    # Variáveis do template WhatsApp
    # (Exemplo → personalize conforme seu template)
    vars_json = json.dumps({
        "nome": nome
    })

    try:
        mensagem = client.messages.create(
            from_=FROM_WPP,
            to=f"whatsapp:+{telefone}",
            content_sid="COLOQUE_SEU_CONTENT_SID_AQUI",
            content_variables=vars_json
        )

        return jsonify({"status": "ok", "sid": mensagem.sid})

    except Exception as e:
        return jsonify({"status": "erro", "detalhes": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
