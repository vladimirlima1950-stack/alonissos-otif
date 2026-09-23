import os
import base64
from datetime import datetime, date
import duckdb
import pandas as pd
import requests
import matplotlib.pyplot as plt
from io import BytesIO

# ============================================================
# Função de LOG (console + arquivo)
# ============================================================

def log(msg):
    print(msg)

    log_path = os.path.join("uploads", "log.txt")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as e:
        print(f"Falha ao escrever log: {e}")


# ============================================================
# 1) Validação dos CSVs
# ============================================================

def validar_csv_pedidos(caminho_pedidos: str):
    if not os.path.exists(caminho_pedidos):
        return False, "Arquivo de pedidos não encontrado."

    try:
        df = duckdb.read_csv(
            caminho_pedidos,
            header=True,
            sep=";",
            auto_detect=True,
            all_varchar=True
        ).df()
    except Exception as e:
        return False, f"Erro ao ler pedidos: {e}"

    if df.shape[1] != 5:
        return False, "Arquivo de pedidos deve ter exatamente 5 colunas."

    return True, "Arquivo de pedidos recebido e validado."


def validar_csv_faturamentos(caminho_faturamentos: str):
    if not os.path.exists(caminho_faturamentos):
        return False, "Arquivo de faturamentos não encontrado."

    try:
        df = duckdb.read_csv(
            caminho_faturamentos,
            header=True,
            sep=";",
            auto_detect=True,
            all_varchar=True
        ).df()
    except Exception as e:
        return False, f"Erro ao ler faturamentos: {e}"

    if df.shape[1] != 5:
        return False, "Arquivo de faturamentos deve ter exatamente 5 colunas."

    return True, "Arquivo de faturamentos recebido e validado."


# ============================================================
# 2) Processamento OTIF
# ============================================================

def processar_otif(caminho_pedidos: str, caminho_faturamentos: str):
    try:
        log("############################################################")
        log(f"# OTIF EXECUTADO EM {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("############################################################")

        log("Iniciando OTIF...")

        pedidos = duckdb.read_csv(
            caminho_pedidos,
            header=True,
            sep=";",
            auto_detect=True,
            all_varchar=True
        ).df()

        fatur = duckdb.read_csv(
            caminho_faturamentos,
            header=True,
            sep=";",
            auto_detect=True,
            all_varchar=True
        ).df()

        log(f"Pedidos lidos: {len(pedidos)} linhas")
        log(f"Faturamentos lidos: {len(fatur)} linhas")

        pedidos.columns = ["ordem", "cliente", "dta_desejada", "sku", "qde_pedida"]
        fatur.columns   = ["dta_efetiva", "cliente", "sku", "qde_fatur", "numero_ordem"]

        log("Convertendo quantidades...")

        pedidos["qde_pedida"] = pd.to_numeric(pedidos["qde_pedida"], errors="coerce").fillna(0)
        pedidos.loc[pedidos["qde_pedida"] < 0, "qde_pedida"] = 0

        fatur["qde_fatur"] = pd.to_numeric(fatur["qde_fatur"], errors="coerce").fillna(0)
        fatur.loc[fatur["qde_fatur"] < 0, "qde_fatur"] = 0

        log("Convertendo datas...")

        pedidos["dta_desejada_amer"] = pd.to_datetime(
            pedidos["dta_desejada"], errors="coerce", dayfirst=True
        )

        ano_ref = date.today().year
        mes_ref = date.today().month - 2
        if mes_ref <= 0:
            mes_ref += 12
            ano_ref -= 1
        data_padrao = date(ano_ref, mes_ref, 1)

        fatur["dta_efetiva"] = fatur["dta_efetiva"].replace("", None)
        fatur["dta_efetiva_amer"] = pd.to_datetime(
            fatur["dta_efetiva"], errors="coerce", dayfirst=True
        )
        fatur["dta_efetiva_amer"] = fatur["dta_efetiva_amer"].fillna(data_padrao)

        log("Executando resumo de faturamento...")

        resumo = fatur.groupby(["numero_ordem", "sku"]).agg(
            max_data=("dta_efetiva_amer", "max"),
            tot_fatur=("qde_fatur", "sum")
        ).reset_index()

        log("Executando merge pedidos + faturamentos...")

        ped_fatur = pd.merge(
            pedidos,
            fatur,
            left_on=["ordem", "sku"],
            right_on=["numero_ordem", "sku"],
            how="left"
        )

        ped_fatur = pd.merge(
            ped_fatur,
            resumo,
            left_on=["ordem", "sku"],
            right_on=["numero_ordem", "sku"],
            how="left"
        )

        log(f"Linhas após merge: {len(ped_fatur)}")

        log("Calculando pontuações OTIF...")

        ped_fatur["max_data"] = ped_fatur["max_data"].fillna(pd.NaT)
        ped_fatur["tot_fatur"] = ped_fatur["tot_fatur"].fillna(0)

        ped_fatur["pontua_data"] = (
            ped_fatur["max_data"] <= ped_fatur["dta_desejada_amer"]
        ).astype(int)

        ped_fatur["pontua_qde"] = (
            ped_fatur["tot_fatur"] >= ped_fatur["qde_pedida"]
        ).astype(int)

        ped_fatur["pontua_total"] = (
            (ped_fatur["pontua_data"] + ped_fatur["pontua_qde"]) == 2
        ).astype(int)

        ped_fatur["ano"] = ped_fatur["dta_desejada_amer"].dt.year
        ped_fatur["mes"] = ped_fatur["dta_desejada_amer"].dt.month

        consol_fase2 = ped_fatur.groupby(["ano", "mes"]).agg(
            total_linhas=("sku", "count"),
            linhas_atendidas=("pontua_total", "sum")
        ).reset_index()

        consol_fase2["nivel_servico_perct"] = (
            consol_fase2["linhas_atendidas"] / consol_fase2["total_linhas"] * 1.0
        )

        log("Calculando backorder...")

        fase3 = ped_fatur[ped_fatur["tot_fatur"] < ped_fatur["qde_pedida"]].copy()
        fase3["dias_pendentes"] = (
            pd.Timestamp(date.today()) - fase3["dta_desejada_amer"]
        ).dt.days

        fase4 = pd.DataFrame({
            "total_ordens": [fase3["ordem"].nunique()],
            "total_dias": [fase3["dias_pendentes"].sum()]
        })
        fase4["idade_backorder"] = (
            fase4["total_dias"] / fase4["total_ordens"]
            if fase4["total_ordens"][0] > 0 else 0
        )

        # ============================================================
        # 3) Criar gráfico OTIF
        # ============================================================

        log("Gerando gráfico OTIF...")

        consol_fase2["ano_mes"] = consol_fase2["ano"].astype(str) + "-" + consol_fase2["mes"].astype(str)

        plt.figure(figsize=(10, 5))
        plt.plot(consol_fase2["ano_mes"], consol_fase2["nivel_servico_perct"],
                 marker="o", color="#2563eb")
        plt.title("Nível de Serviço OTIF")
        plt.xlabel("Ano-Mês")
        plt.ylabel("Percentual (%)")
        plt.grid(True)
        plt.xticks(rotation=45)

        img_data = BytesIO()
        plt.savefig(img_data, format="png", bbox_inches="tight")
        plt.close()
        img_data.seek(0)

        # ============================================================
        # 4) Gerar Excel com gráfico na primeira aba
        # ============================================================

        log("Gerando Excel...")

        pasta_saida = os.path.dirname(caminho_pedidos)
        arquivo_xlsx = os.path.join(
            pasta_saida,
            f"OTIF_COMPLETO_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

        with pd.ExcelWriter(arquivo_xlsx, engine="xlsxwriter") as writer:
            workbook  = writer.book

            # Formato percentual com duas casas
            percent_fmt = workbook.add_format({'num_format': '0.00%'})

            # Aba do gráfico
            worksheet_graf = workbook.add_worksheet("Grafico_OTIF")
            worksheet_graf.insert_image("B2", "grafico.png", {"image_data": img_data})

            # Aba Ped_Fatur
            ped_fatur.to_excel(writer, sheet_name="Ped_Fatur", index=False)

            # Aba Nivel_Servico
            consol_fase2.to_excel(writer, sheet_name="Nivel_Servico", index=False)
            ws_ns = writer.sheets["Nivel_Servico"]

            # Detecta automaticamente a coluna percentual
            for col_idx, col_name in enumerate(consol_fase2.columns):
                if col_name.lower() == "nivel_servico_perct":
                    ws_ns.set_column(col_idx, col_idx, 12, percent_fmt)

            # Aba Backorder_Detalhes
            fase3.to_excel(writer, sheet_name="Backorder_Detalhes", index=False)

            # Aba Backorder_Resumo
            fase4.to_excel(writer, sheet_name="Backorder_Resumo", index=False)
            ws_br = writer.sheets["Backorder_Resumo"]

            # Formato numérico com duas casas decimais
            num_fmt = workbook.add_format({'num_format': '0.00'})

            # Detecta automaticamente a coluna idade_backorder
            for col_idx, col_name in enumerate(fase4.columns):
                if col_name.lower() == "idade_backorder":
                    ws_br.set_column(col_idx, col_idx, 12, num_fmt)     


        log(f"Excel gerado: {arquivo_xlsx}")
        log("Processamento OTIF concluído.")

        return arquivo_xlsx

    except Exception as e:
        log(f"Erro interno: {e}")
        raise Exception(f"Falha ao processar OTIF: {e}")


# ============================================================
# 5) Envio de e-mail via RESEND
# ============================================================

def enviar_email_otif(
        arquivo_xlsx: str,
        email_destino: str,
        nome: str = "Cliente"
):


        
    log(f"Enviando e-mail OTIF para {email_destino} via Resend...")

    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    if not RESEND_API_KEY:
        log("ERRO: RESEND_API_KEY não configurada no Railway.")
        return False

    with open(arquivo_xlsx, "rb") as f:
        arquivo_bytes = f.read()

    arquivo_base64 = base64.b64encode(arquivo_bytes).decode("utf-8")
    primeiro_nome = contato.split()[0] if contato else "Cliente"

    payload = {
        "from": "MUPE Consultoria <noreply@mupeconsult.com>",
        "to": email_destino,
        "subject": "Relatório Nível de Serviço aos Clientes - OTIF",
        

        "html": """
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            Olá, {primeiro_nome}!
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            O módulo <strong>Avaliação do Nível de Serviço</strong> foi processado com sucesso.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            A planilha anexa permite avaliar o nível de atendimento aos clientes ao longo do período analisado.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            A análise do nível de serviço mostra qual percentual da demanda foi atendido integralmente e permite identificar períodos de melhora ou deterioração do desempenho operacional.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            O gráfico de evolução do nível de serviço facilita a identificação de tendências ao longo do tempo e ajuda a verificar se as ações adotadas pela empresa estão produzindo os resultados esperados.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            O detalhamento dos back orders permite identificar os itens responsáveis pelos pedidos pendentes, auxiliando na priorização das compras, na redução das rupturas e na recuperação das vendas perdidas.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            A análise da idade média dos back orders ajuda a medir há quanto tempo os clientes aguardam atendimento, indicando situações que podem comprometer a satisfação dos clientes e a fidelização.
            </p>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            <strong>Por onde começar?</strong>
            </p>
            
            <ol style='font-family: Arial; font-size: 15px; color: #333;'>
            <li>Verifique o nível de serviço médio do período e compare-o com a meta estabelecida pela empresa.</li>
            <li>Analise os meses com pior desempenho para identificar possíveis causas das rupturas.</li>
            <li>Identifique os itens que mais geraram back orders e avalie se os estoques de segurança são adequados.</li>
            <li>Priorize o atendimento dos back orders mais antigos para minimizar impactos no relacionamento com os clientes.</li>
            <li>Utilize os resultados deste módulo em conjunto com as análises de estoques, compras e fornecedores para identificar as principais causas das perdas de vendas.</li>
            <li>Acompanhe a evolução do nível de serviço ao longo do tempo para verificar se as ações corretivas estão produzindo resultados efetivos.</li>
            </ol>
            
            <p style='font-family: Arial; font-size: 15px; color: #333;'>
            Atenciosamente,<br>
            <strong>MUPE Consultoria</strong>
            </p>
            """
            ,


        "attachments": [
            {
                "filename": os.path.basename(arquivo_xlsx),
                "content": arquivo_base64,
                "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }
        ]
    }

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if 200 <= response.status_code < 300:
        log("E-mail enviado com sucesso via Resend.")
        return True
    else:
        log(f"Erro ao enviar e-mail via Resend: {response.text}")
        return False
