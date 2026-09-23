<?php
session_start();
require 'conexao.php'; // usa o mesmo $pdo do login.php

if (!isset($_SESSION['logado']) || $_SESSION['logado'] !== true) {
    header("Location: login.php");
    exit;
}

$cliente = $_SESSION['usuario'];
$emailCliente = $_SESSION['email'];
$nomeClienteTela = $_SESSION['nome'] ?? $cliente;

$railway_base = "https://cozy-vision-production-6526.up.railway.app";

/* ============================================================
   FUNÇÃO ORIGINAL — NÃO ALTERADA
============================================================ */
function enviarArquivoOTIF($campo, $endpoint, $railway_base) {
    if (!isset($_FILES[$campo]) || $_FILES[$campo]['error'] !== UPLOAD_ERR_OK) {
        return ['status' => 'erro', 'mensagem' => "Arquivo '$campo' não enviado."];
    }

    $arquivo = $_FILES[$campo];
    $ext = strtolower(pathinfo($arquivo['name'], PATHINFO_EXTENSION));

    if ($ext !== "csv") {
        return ['status' => 'erro', 'mensagem' => "Erro: o arquivo '$campo' deve ser .csv"];
    }

    $mime = mime_content_type($arquivo['tmp_name']);

    $curl = curl_init();
    curl_setopt_array($curl, [
        CURLOPT_URL => "$railway_base/$endpoint",
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => [
            "file" => curl_file_create($arquivo['tmp_name'], $mime, basename($arquivo['name']))
        ],
        CURLOPT_RETURNTRANSFER => true
    ]);

    $resposta = curl_exec($curl);
    curl_close($curl);

    return json_decode($resposta, true);
}

$mensagens = [];
$processado = false;

/* ============================================================
   PROCESSAMENTO ORIGINAL — NÃO ALTERADO
============================================================ */
if ($_SERVER['REQUEST_METHOD'] === 'POST') {

    $respPedidos = enviarArquivoOTIF("pedidos", "upload_pedidos", $railway_base);
    $respFaturamentos = enviarArquivoOTIF("faturamentos", "upload_faturamentos", $railway_base);

    $pedidosOK = ($respPedidos['status'] === 'ok');
    $faturamentosOK = ($respFaturamentos['status'] === 'ok');

    $mensagens[] = "Pedidos: " . ($respPedidos['mensagem'] ?? '');
    $mensagens[] = "Faturamentos: " . ($respFaturamentos['mensagem'] ?? '');

    /* ============================================================
       SOMENTE REGISTRA SE AMBOS ESTIVEREM OK (como você confirmou)
    ============================================================ */
    if ($pedidosOK && $faturamentosOK) {

        // REGISTRA O UPLOAD DO MÓDULO OTIF
        $stmt = $pdo->prepare("INSERT INTO uploads (cliente_id, tipo_arquivo) VALUES (:cliente_id, 'otif')");
        $stmt->execute([':cliente_id' => $cliente]);

        // PROCESSAMENTO ORIGINAL — NÃO ALTERADO
        $curl = curl_init();
        curl_setopt_array($curl, [
            CURLOPT_URL => "$railway_base/processar_otif?email="
			. urlencode($emailCliente)
			. "&nome="
			. urlencode($nomeClienteTela),
            CURLOPT_RETURNTRANSFER => false,
            CURLOPT_TIMEOUT => 2
        ]);

        curl_exec($curl);
        curl_close($curl);

        $mensagens[] = "Processamento iniciado. Você receberá o resultado por e‑mail.";
        $processado = true;
    }
}
?>

<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>Envio de Arquivos Nível de Serviço ao Cliente - OTIF - MUPE Consultoria</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #f3f4f6;
    margin: 0;
    padding: 0;
}

.container {
    max-width: 700px;
    margin: 40px auto;
    background: #ffffff;
    padding: 30px;
    border-radius: 10px;
    box-shadow: 0 8px 20px rgba(0,0,0,0.08);
}

h2 {
    margin-top: 0;
    font-size: 24px;
    color: #1f2933;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 8px;
}

h3 {
    margin-top: 25px;
    color: #374151;
}

label {
    font-weight: bold;
    margin-top: 15px;
    display: block;
}

input[type="file"] {
    margin-top: 5px;
}

button {
    width: 100%;
    padding: 12px;
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 15px;
    cursor: pointer;
    margin-top: 20px;
}

button:hover {
    background: #1d4ed8;
}

.msg {
    background: #e0f2fe;
    padding: 10px;
    border-radius: 6px;
    margin-top: 15px;
    color: #0369a1;
    font-size: 14px;
}

.sucesso {
    background: #dcfce7;
    padding: 15px;
    border-radius: 6px;
    margin-top: 20px;
    color: #166534;
    font-size: 15px;
    border-left: 5px solid #16a34a;
}

.botao-voltar {
    display: inline-block;
    margin-top: 20px;
    padding: 12px 20px;
    background: #2563eb;
    color: white;
    border-radius: 6px;
    text-decoration: none;
    font-size: 15px;
}

.botao-voltar:hover {
    background: #1d4ed8;
}
</style>

</head>

<body>

<div class="container">

<h2>Envio de Arquivos Nível de Serviço ao Cliente - OTIF</h2>

<p>Cliente identificado: <strong><?= htmlspecialchars($_SESSION['nome']) ?></strong></p>

<form method="POST" enctype="multipart/form-data">

<h3>Arquivo de Pedidos (.csv)</h3>

<p style="font-size:14px; color:#374151; background:#f9fafb; padding:10px; border-left:4px solid #2563eb; border-radius:6px;">
    O arquivo deve conter:<br>
    1) identificação do pedido na primeira coluna;<br>
    2) identificação do cliente na segunda coluna;<br>
    3) data desejada pelo cliente no formato <strong>DD/MM/AAAA</strong> na terceira coluna;<br>
    4) identificação do sku/artigo/produto/item na quarta coluna;<br>
    5) quantidade pedida pelo cliente na quinta coluna.<br><br>
    Todas as colunas devem ser formatadas como <strong>texto</strong>, exceto a coluna contendo datas.
</p>

<input type="file" name="pedidos" required>


<h3>Arquivo de Faturamentos (.csv)</h3>

<p style="font-size:14px; color:#374151; background:#f9fafb; padding:10px; border-left:4px solid #2563eb; border-radius:6px;">
    O arquivo deve conter:<br>
    1) data do faturamento no formato <strong>DD/MM/AAAA</strong> na primeira coluna;<br>
    2) identificação do cliente na segunda coluna;<br>
    3) identificação do sku/artigo/produto/item na terceira coluna;<br>
    4) quantidade faturada na quarta coluna;<br>
    5) identificação do pedido na quinta coluna.<br><br>
    Todas as colunas devem ser formatadas como <strong>texto</strong>, exceto a coluna contendo datas.
</p>

<input type="file" name="faturamentos" required>

<button type="submit">Enviar arquivos e iniciar processamento</button>

</form>

<?php if (!empty($mensagens)): ?>
<div class="msg">
    <?php foreach ($mensagens as $m): ?>
        <p><?= htmlspecialchars($m) ?></p>
    <?php endforeach; ?>
</div>
<?php endif; ?>

<?php if ($processado): ?>
<div class="sucesso">
    <p><strong>Arquivos enviados com sucesso!</strong></p>
    <p>O processamento foi iniciado automaticamente.</p>
    <p>O resultado será enviado para o e‑mail cadastrado.</p>
</div>

<a href="https://mupeconsult.com/" class="botao-voltar">Voltar ao site MUPE Consultoria</a>
<?php endif; ?>

</div>

</body>
</html>
