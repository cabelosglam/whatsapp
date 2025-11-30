<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Formulário WhatsApp Automático</title>

    <style>
        body {
            font-family: Arial;
            background: #f3f3f3;
            padding: 40px;
        }
        .box {
            background: white;
            padding: 25px;
            max-width: 420px;
            margin: auto;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0,0,0,.1);
        }
        input {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
        }
        button {
            margin-top: 20px;
            width: 100%;
            padding: 12px;
            background: #00c853;
            border: none;
            color: white;
            font-size: 16px;
            cursor: pointer;
        }
        button:hover {
            background: #00a846;
        }
        #resultado {
            margin-top: 15px;
            font-size: 14px;
        }
    </style>
</head>
<body>

<div class="box">
    <h2>Receba informações no WhatsApp</h2>

    <form id="form">
        <input type="text" name="nome" placeholder="Seu nome" required>
        <input type="text" name="telefone" placeholder="DDD + Número (ex: 5511999999999)" required>

        <button type="submit">Enviar</button>
    </form>

    <p id="resultado"></p>
</div>

<script>
document.getElementById("form").addEventListener("submit", async (e) => {
    e.preventDefault();

    const formData = new FormData(e.target);

    const r = await fetch("/enviar", {
        method: "POST",
        body: formData
    });

    const resposta = await r.json();

    if (resposta.status === "ok") {
        document.getElementById("resultado").innerHTML =
            "Mensagem enviada com sucesso! ✔️";
    } else {
        document.getElementById("resultado").innerHTML =
            "Erro: " + resposta.detalhes;
    }
});
</script>

</body>
</html>
