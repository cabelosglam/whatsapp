import json
from google_sheets import ler_linhas
from app import processar_novo_lead_sheet

MEMORY_FILE = "sheet_memory.json"


def carregar_memoria():
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def salvar_memoria(memoria):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memoria, f, indent=4)


def verificar_planilha():
    print("🔎 Verificando planilha...")

    memoria = carregar_memoria()
    linhas = ler_linhas()

    novos = [l for l in linhas if l not in memoria]

    for linha in novos:
        nome = linha.get("nome") or linha.get("Nome")
        telefone = linha.get("telefone") or linha.get("Telefone")
        email = linha.get("email") or linha.get("Email")

        print(f"⚡ Novo lead encontrado: {nome} | {telefone}")

        processar_novo_lead_sheet(nome, telefone, email)

        memoria.append(linha)

    salvar_memoria(memoria)

    print("✔ Verificação concluída.")
