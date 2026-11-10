import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict

try:
    import pdfplumber
except ImportError:
    print("Instale a biblioteca com: pip install pdfplumber")
    raise


# =========================
# CONFIGURAÇÕES FIXAS
# =========================
DATA_INSERIR_FIXA = "11/12/2026"
NAO_ENCONTRADO = "não encontrado"


@dataclass
class LinhaEntrada:
    cd: str
    razao_social: str
    cnpj: str
    responsavel_atual: str
    report_direto: str
    segmento: str
    modelo_ali: str
    bv_estimado_mes: str
    produto_blindado: str
    percentual_ali: str
    valor_ali_ano: str
    valor_ate_jan26: str
    valor_fev_abr26: str
    valor_maio26: str
    produto_destino: str
    prazo_blindagem: str
    data_inicio: str
    data_fim: str
    data_inserir: str
    expirar_dias: str


def ler_pdf_texto(caminho_pdf: str) -> str:
    partes = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            partes.append(texto)
    return "\n".join(partes)


def limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def formatar_moeda_br(valor: float) -> str:
    # Saída no padrão que você vinha usando nas linhas
    return f"R$ {valor:,.2f}"


def extrair_cnpjs(texto: str) -> List[str]:
    encontrados = re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    limpos = [limpar_cnpj(c) for c in encontrados]
    # Remove duplicados preservando ordem
    vistos = set()
    unicos = []
    for c in limpos:
        if c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos


def extrair_data_assinatura(texto: str) -> Optional[str]:
    # Pega datas como 11-02-2026 ou 23-07-2025
    datas = re.findall(r"\b(\d{2})-(\d{2})-(\d{4})\b", texto)
    if datas:
        d, m, a = datas[-1]
        return f"{int(m)}/{int(d)}/{a}"
    return None


def somar_meses(data_mmddaaaa: str, meses: int) -> str:
    from datetime import datetime
    from calendar import monthrange

    dt = datetime.strptime(data_mmddaaaa, "%m/%d/%Y")
    novo_mes = dt.month - 1 + meses
    ano = dt.year + novo_mes // 12
    mes = novo_mes % 12 + 1
    dia = min(dt.day, monthrange(ano, mes)[1])
    return f"{mes}/{dia}/{ano}"


def extrair_prazo_meses(texto: str) -> Optional[str]:
    m = re.search(r"vigorará pelo período de\s+(\d+)\s+MESES", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def extrair_bv(texto: str) -> Optional[float]:
    qtd = None
    alim = None
    ref = None

    m_qtd = re.search(r"Quantidade estimada de CARTÕES\s+(\d+)", texto, re.IGNORECASE)
    if m_qtd:
        qtd = int(m_qtd.group(1))

    m_alim = re.search(r"Valor médio mensal da Carteira ALIMENTAÇÃO.*?\(R\$\):\s*([\d.,NAna]+)", texto, re.IGNORECASE)
    if m_alim:
        valor = m_alim.group(1).strip()
        alim = None if valor.upper() == "NA" else float(valor.replace(".", "").replace(",", "."))

    m_ref = re.search(r"Valor médio mensal da Carteira REFEIÇÃO.*?\(R\$\):\s*([\d.,NAna]+)", texto, re.IGNORECASE)
    if m_ref:
        valor = m_ref.group(1).strip()
        ref = None if valor.upper() == "NA" else float(valor.replace(".", "").replace(",", "."))

    if qtd is None:
        return None

    total = 0.0
    if alim is not None:
        total += qtd * alim
    if ref is not None:
        total += qtd * ref

    return total if total > 0 else None


def extrair_tipo_e_valor_ali(texto: str) -> Dict[str, Optional[str]]:
    # Cenário percentual por faixas
    perc_ate_jan = re.search(r"até\s*31/01/26\s*([0-9,.]+%)", texto, re.IGNORECASE)
    perc_fev_abr = re.search(r"01/02/26\s*até\s*30/04/26\s*([0-9,.]+%)", texto, re.IGNORECASE)
    perc_maio = re.search(r"a partir de\s*01/05/26.*?([0-9,.]+%)", texto, re.IGNORECASE)

    if perc_ate_jan or perc_fev_abr or perc_maio:
        return {
            "tipo": "percentual",
            "percentual_principal": perc_ate_jan.group(1) if perc_ate_jan else None,
            "valor_fixo": None,
            "valor_ate_jan26": perc_ate_jan.group(1) if perc_ate_jan else None,
            "valor_fev_abr26": perc_fev_abr.group(1) if perc_fev_abr else None,
            "valor_maio26": perc_maio.group(1) if perc_maio else None,
        }

    # Cenário percentual simples
    perc_simples = re.search(r"CRÉDITO ALIMENTAÇÃO DO TRABALHADOR\s*% a ser aplicado\s*([0-9,.]+%)", texto, re.IGNORECASE)
    if perc_simples:
        return {
            "tipo": "percentual",
            "percentual_principal": perc_simples.group(1),
            "valor_fixo": None,
            "valor_ate_jan26": None,
            "valor_fev_abr26": None,
            "valor_maio26": None,
        }

    # Cenário valor fixo anual
    valor_fixo = re.search(r"Valor anual total \(fixo / irreajustável\)\s*R\$\s*([\d.]+,\d{2})", texto, re.IGNORECASE)
    if valor_fixo:
        valor = float(valor_fixo.group(1).replace(".", "").replace(",", "."))
        return {
            "tipo": "fixo",
            "percentual_principal": None,
            "valor_fixo": formatar_moeda_br(valor),
            "valor_ate_jan26": None,
            "valor_fev_abr26": None,
            "valor_maio26": None,
        }

    return {
        "tipo": None,
        "percentual_principal": None,
        "valor_fixo": None,
        "valor_ate_jan26": None,
        "valor_fev_abr26": None,
        "valor_maio26": None,
    }


def extrair_produto_destino(texto: str) -> Optional[str]:
    m = re.search(r"Modalidade de Serviço PLUXEE para\s+disponibilização.*?(Alimentação|Refeição / Alimentação|Refeição)", texto, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    valor = m.group(1).strip()
    if valor.lower() == "refeição / alimentação":
        return "Refeição e Alimentação"
    return valor


def extrair_expirar_dias(texto: str) -> Optional[str]:
    # Prioriza 180 ou 90 ligados à cláusula de utilização
    m180 = re.search(r"prazo de\s*180\s*\(cento e oitenta\)\s*dias", texto, re.IGNORECASE)
    if m180:
        return "180"
    m90 = re.search(r"prazo de\s*90\s*\(noventa\)\s*dias", texto, re.IGNORECASE)
    if m90:
        return "90"
    return None


def carregar_linha_texto(texto_linha: str) -> LinhaEntrada:
    partes = texto_linha.rstrip("\n").split("\t")
    while len(partes) < 20:
        partes.append("")
    return LinhaEntrada(*partes[:20])


def montar_linha_saida(linha: LinhaEntrada, texto_pdf: str) -> str:
    cnpjs_pdf = extrair_cnpjs(texto_pdf)
    prazo = extrair_prazo_meses(texto_pdf) or (linha.prazo_blindagem or NAO_ENCONTRADO)
    data_inicio = extrair_data_assinatura(texto_pdf) or NAO_ENCONTRADO
    data_fim = somar_meses(data_inicio, int(prazo)) if data_inicio != NAO_ENCONTRADO and prazo.isdigit() else NAO_ENCONTRADO
    bv = extrair_bv(texto_pdf)
    tipo_info = extrair_tipo_e_valor_ali(texto_pdf)
    produto_destino = extrair_produto_destino(texto_pdf) or (linha.produto_destino or NAO_ENCONTRADO)
    expirar = extrair_expirar_dias(texto_pdf) or NAO_ENCONTRADO

    # CNPJ: se o PDF trouxe algo, usa. Se não, mantém o da linha.
    cnpj_saida = "\n".join(cnpjs_pdf) if cnpjs_pdf else (linha.cnpj or NAO_ENCONTRADO)

    bv_saida = formatar_moeda_br(bv) if bv is not None else (linha.bv_estimado_mes or NAO_ENCONTRADO)

    percentual = tipo_info["percentual_principal"] or ""
    valor_fixo = tipo_info["valor_fixo"] or ""

    valor_ate_jan26 = tipo_info["valor_ate_jan26"] or linha.valor_ate_jan26
    valor_fev_abr26 = tipo_info["valor_fev_abr26"] or linha.valor_fev_abr26
    valor_maio26 = tipo_info["valor_maio26"] or linha.valor_maio26

    # Se nada foi encontrado em percentual/fixo, preenche não encontrado em ambos os campos editáveis
    if not percentual and not valor_fixo:
        percentual = NAO_ENCONTRADO
        valor_fixo = NAO_ENCONTRADO

    campos = [
        linha.cd,
        linha.razao_social,
        cnpj_saida,
        linha.responsavel_atual,
        linha.report_direto,
        linha.segmento,
        linha.modelo_ali,
        bv_saida,
        linha.produto_blindado,
        percentual,
        valor_fixo,
        valor_ate_jan26,
        valor_fev_abr26,
        valor_maio26,
        produto_destino,
        prazo,
        data_inicio,
        data_fim,
        DATA_INSERIR_FIXA,
        expirar,
    ]
    return "\t".join(campos)


def main():
    if len(sys.argv) < 3:
        print("Uso: python protocolo_p_robo.py contrato.pdf linha.txt")
        print("No arquivo linha.txt, coloque a linha inteira separada por TAB.")
        return

    caminho_pdf = sys.argv[1]
    caminho_linha = sys.argv[2]

    texto_pdf = ler_pdf_texto(caminho_pdf)
    texto_linha = Path(caminho_linha).read_text(encoding="utf-8")
    linha = carregar_linha_texto(texto_linha)
    saida = montar_linha_saida(linha, texto_pdf)

    print("\nLINHA FINAL:\n")
    print(saida)


if __name__ == "__main__":
    main()
