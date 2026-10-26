"""
gerar_dados_simulados.py
========================

Gera a base FICTÍCIA do projeto Demand Planning Accuracy Dashboard, simulando
o que sairia de um ERP (pedidos/faturamento), de uma ferramenta de planejamento
de demanda (ciclos de S&OP com versões e lags) e do controle de estoque.

A ideia é que os dados tenham a "bagunça" do dia a dia de um planejador:
  * sazonalidade por categoria, crescimento, feriados e dias úteis;
  * promoções (algumas canceladas, algumas cadastradas em cima da hora);
  * lançamentos com carga inicial, descontinuações e troca de SKU (phase-in/out);
  * canibalização entre SKUs, aumento de preço com compra antecipada;
  * entrada e saída de clientes, concorrente novo derrubando a demanda;
  * ruptura (cortes por falta de estoque), bloqueio de crédito, devoluções,
    bonificações e perdas por vencimento/obsolescência;
  * forecast estatístico x comercial x consenso, com erro crescendo pelo lag.

Tudo é gerado a partir de uma semente fixa (SEED), então rodar de novo gera
exatamente os mesmos arquivos. Troque a semente para obter outra "realidade".

Uso:
    python src/gerar_dados_simulados.py              # grava em Dados/
    python src/gerar_dados_simulados.py --saida X    # grava na pasta X
    python src/gerar_dados_simulados.py --com-problemas
        # também gera Dados/_brutos_com_problemas/ com erros típicos de
        # cadastro/extração para treinar limpeza de dados no ETL

Todos os nomes de clientes, marcas, pessoas e números são inventados.
"""

from __future__ import annotations

import argparse
import bisect
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil.easter import easter

# =============================================================================
# CONFIGURAÇÃO GERAL
# =============================================================================
SEED = 42
INICIO_VENDAS = date(2024, 1, 1)
FIM_VENDAS = date(2026, 9, 30)        # último dia com faturamento fechado
FIM_CALENDARIO = date(2027, 3, 31)    # cobre o horizonte do último ciclo
DATA_REFERENCIA = date(2026, 10, 26)  # "hoje" para status de ciclo de vida
PRIMEIRO_CICLO = 3                    # abr/2024 (precisa de 3 meses de histórico)
LAGS_POR_CICLO = 3                    # cada ciclo projeta lag 0..3
LAGS_ULTIMO_CICLO = 5                 # o ciclo mais recente projeta lag 0..5
FMT = "%d/%m/%Y"                      # mesmo formato de data dos CSVs originais

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "Dados"

rng = np.random.default_rng(SEED)


def mes_idx(d: date) -> int:
    """Índice do mês a partir de jan/2024 (jan/2024 = 0)."""
    return (d.year - 2024) * 12 + d.month - 1


def mes_data(i: int) -> date:
    return date(2024 + i // 12, i % 12 + 1, 1)


def fim_mes(i: int) -> date:
    return mes_data(i + 1) - timedelta(days=1)


N_MESES_REAL = mes_idx(FIM_VENDAS) + 1        # 33 meses fechados
N_MESES_TOTAL = mes_idx(FIM_CALENDARIO) + 1   # 39 meses (inclui futuro)
ULTIMO_CICLO = N_MESES_REAL                   # out/2026

# =============================================================================
# CALENDÁRIO, FERIADOS E DIAS ÚTEIS
# =============================================================================


def feriados_nacionais(ano: int) -> dict[date, tuple[str, str]]:
    p = easter(ano)
    nac = "Feriado Nacional"
    fac = "Ponto Facultativo"
    return {
        date(ano, 1, 1): ("Confraternização Universal", nac),
        p - timedelta(days=48): ("Carnaval", fac),
        p - timedelta(days=47): ("Carnaval", fac),
        p - timedelta(days=2): ("Sexta-feira Santa", nac),
        date(ano, 4, 21): ("Tiradentes", nac),
        date(ano, 5, 1): ("Dia do Trabalho", nac),
        p + timedelta(days=60): ("Corpus Christi", fac),
        date(ano, 9, 7): ("Independência do Brasil", nac),
        date(ano, 10, 12): ("Nossa Senhora Aparecida", nac),
        date(ano, 11, 2): ("Finados", nac),
        date(ano, 11, 15): ("Proclamação da República", nac),
        date(ano, 11, 20): ("Dia Nacional de Zumbi e da Consciência Negra", nac),
        date(ano, 12, 25): ("Natal", nac),
    }


def n_esimo_dia_semana(ano: int, mes: int, dia_semana: int, n: int) -> date:
    d = date(ano, mes, 1)
    return d + timedelta(days=(dia_semana - d.weekday()) % 7 + 7 * (n - 1))


def datas_comerciais(ano: int) -> dict[date, str]:
    return {
        easter(ano): "Páscoa",
        n_esimo_dia_semana(ano, 5, 6, 2): "Dia das Mães",
        date(ano, 6, 12): "Dia dos Namorados",
        n_esimo_dia_semana(ano, 8, 6, 2): "Dia dos Pais",
        n_esimo_dia_semana(ano, 11, 3, 4) + timedelta(days=1): "Black Friday",
        date(ano, 12, 24): "Véspera de Natal",
        date(ano, 12, 31): "Véspera de Ano Novo",
    }


FERIADOS: dict[date, tuple[str, str]] = {}
COMERCIAIS: dict[date, str] = {}
for _ano in range(2023, 2028):
    FERIADOS.update(feriados_nacionais(_ano))
    COMERCIAIS.update(datas_comerciais(_ano))


def eh_dia_util(d: date) -> bool:
    # Carnaval é tratado como dia NÃO útil (operação parada na prática);
    # Corpus Christi é tratado como útil (feriado só em parte das cidades).
    if d.weekday() >= 5:
        return False
    f = FERIADOS.get(d)
    return not (f and f[0] != "Corpus Christi")


DIAS_UTEIS = [
    date(2023, 12, 1) + timedelta(days=i)
    for i in range((date(2027, 5, 1) - date(2023, 12, 1)).days)
    if eh_dia_util(date(2023, 12, 1) + timedelta(days=i))
]


def proximo_dia_util(d: date, estritamente_depois: bool = False) -> date:
    pos = bisect.bisect_right(DIAS_UTEIS, d) if estritamente_depois else bisect.bisect_left(DIAS_UTEIS, d)
    return DIAS_UTEIS[pos]


def gerar_calendario() -> pd.DataFrame:
    nomes_mes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
                 "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    nomes_dia = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
                 "Sexta-feira", "Sábado", "Domingo"]
    linhas = []
    d = INICIO_VENDAS
    while d <= FIM_CALENDARIO:
        iso = d.isocalendar()
        fer = FERIADOS.get(d)
        linhas.append({
            "Data": d,
            "Ano": d.year,
            "Trimestre": (d.month - 1) // 3 + 1,
            "Mes": d.month,
            "Nome_Mes": nomes_mes[d.month - 1],
            "Ano_Mes": f"{d.year}-{d.month:02d}",
            "Primeiro_Dia_Mes": d.replace(day=1),
            "Semana_ISO": iso[1],
            "Ano_Semana_ISO": f"{iso[0]}-S{iso[1]:02d}",
            "Dia_Semana_Num": d.weekday() + 1,
            "Dia_Semana": nomes_dia[d.weekday()],
            "Fim_de_Semana": int(d.weekday() >= 5),
            "Feriado": fer[0] if fer else "",
            "Tipo_Feriado": fer[1] if fer else "",
            "Dia_Util": int(eh_dia_util(d)),
            "Data_Comercial": COMERCIAIS.get(d, ""),
        })
        d += timedelta(days=1)
    cal = pd.DataFrame(linhas)
    cal["Dias_Uteis_Mes"] = cal.groupby("Ano_Mes")["Dia_Util"].transform("sum")
    cal["Dia_Util_do_Mes"] = cal.groupby("Ano_Mes")["Dia_Util"].cumsum() * cal["Dia_Util"]
    return cal


# =============================================================================
# CADASTROS (DIMENSÕES)
# =============================================================================

CDS = [
    dict(ID_CD="CD01", Nome_CD="CD Cajamar", Cidade="Cajamar", UF="SP", Regiao="Sudeste",
         Tipo_Operacao="Operador Logístico", Regioes_Atendidas="Sudeste, Sul, Centro-Oeste"),
    dict(ID_CD="CD02", Nome_CD="CD Jaboatão", Cidade="Jaboatão dos Guararapes", UF="PE", Regiao="Nordeste",
         Tipo_Operacao="Operador Logístico", Regioes_Atendidas="Nordeste, Norte"),
]

# peso = popularidade relativa do SKU no mix (quanto maior, mais vende)
# lanc = lançamento dentro do período simulado | desc = descontinuação
PRODUTOS = [
    # --- Bebidas -----------------------------------------------------------
    dict(id=101, nome="Leite Vegetal Original 1L", cat="Bebidas", sub="Bebida Vegetal 1L", emb="Caixa cartonada", cont="1 L",
         temp="Ambiente", shelf=180, ucx=12, preco=12.90, custo=8.00, cad=date(2021, 3, 15), peso=10.0),
    dict(id=105, nome="Leite Vegetal Zero Açúcar 1L", cat="Bebidas", sub="Bebida Vegetal 1L", emb="Caixa cartonada", cont="1 L",
         temp="Ambiente", shelf=180, ucx=12, preco=13.50, custo=8.30, cad=date(2021, 8, 2), peso=5.0),
    dict(id=106, nome="Leite Vegetal Chocolate 1L", cat="Bebidas", sub="Bebida Vegetal 1L", emb="Caixa cartonada", cont="1 L",
         temp="Ambiente", shelf=180, ucx=12, preco=14.20, custo=8.90, cad=date(2022, 2, 7), peso=4.0),
    dict(id=107, nome="Leite Vegetal Barista 1L", cat="Bebidas", sub="Barista", emb="Caixa cartonada", cont="1 L",
         temp="Ambiente", shelf=180, ucx=12, preco=15.90, custo=9.40, cad=date(2022, 6, 6), peso=3.0),
    dict(id=108, nome="Leite Vegetal Original 200ml", cat="Bebidas", sub="Bebida Vegetal Porção", emb="Caixa cartonada", cont="200 ml",
         temp="Ambiente", shelf=180, ucx=27, preco=3.90, custo=2.30, cad=date(2022, 9, 12), peso=4.0),
    dict(id=109, nome="Leite Vegetal Chocolate 200ml", cat="Bebidas", sub="Bebida Vegetal Porção", emb="Caixa cartonada", cont="200 ml",
         temp="Ambiente", shelf=180, ucx=27, preco=4.20, custo=2.50, lanc=date(2025, 3, 10), peso=3.0),
    dict(id=110, nome="Leite Vegetal Baunilha 1L", cat="Bebidas", sub="Bebida Vegetal 1L", emb="Caixa cartonada", cont="1 L",
         temp="Ambiente", shelf=180, ucx=12, preco=14.20, custo=8.90, cad=date(2023, 4, 3), desc=date(2025, 6, 30), peso=1.2),
    # --- Condimentos -------------------------------------------------------
    dict(id=102, nome="Maionese Vegana 500g", cat="Condimentos", sub="Maionese", emb="Pote", cont="500 g",
         temp="Ambiente", shelf=270, ucx=12, preco=17.50, custo=12.00, cad=date(2021, 3, 15), peso=6.0),
    dict(id=111, nome="Maionese Vegana 250g", cat="Condimentos", sub="Maionese", emb="Pote", cont="250 g",
         temp="Ambiente", shelf=270, ucx=24, preco=9.90, custo=6.40, cad=date(2021, 10, 4), peso=5.0),
    dict(id=112, nome="Maionese Vegana Alho 250g", cat="Condimentos", sub="Maionese Temperada", emb="Pote", cont="250 g",
         temp="Ambiente", shelf=270, ucx=24, preco=10.90, custo=7.00, lanc=date(2024, 9, 2), peso=2.5),
    dict(id=113, nome="Maionese Vegana Bisnaga Food Service 1,01kg", cat="Condimentos", sub="Food Service", emb="Bisnaga", cont="1,01 kg",
         temp="Ambiente", shelf=270, ucx=12, preco=29.90, custo=19.50, cad=date(2022, 3, 14), peso=3.0, fs=True),
    dict(id=114, nome="Maionese Vegana Sachê 7g (pct 168un)", cat="Condimentos", sub="Food Service", emb="Pacote de sachês", cont="168 x 7 g",
         temp="Ambiente", shelf=270, ucx=6, preco=39.90, custo=25.00, cad=date(2023, 1, 9), peso=1.5, fs=True),
    dict(id=115, nome="Maionese Vegana Chipotle 250g", cat="Condimentos", sub="Maionese Temperada", emb="Pote", cont="250 g",
         temp="Ambiente", shelf=270, ucx=24, preco=11.50, custo=7.40, lanc=date(2026, 6, 1), peso=2.0),
    # --- Congelados --------------------------------------------------------
    dict(id=103, nome="Hambúrguer Plant-Based 200g", cat="Congelados", sub="Hambúrguer", emb="Bandeja", cont="2 x 100 g",
         temp="Congelado", shelf=365, ucx=12, preco=22.90, custo=15.00, cad=date(2021, 3, 15), peso=7.0),
    dict(id=116, nome="Hambúrguer Plant-Based Food Service 2kg", cat="Congelados", sub="Food Service", emb="Caixa", cont="20 x 100 g",
         temp="Congelado", shelf=365, ucx=4, preco=119.00, custo=78.00, cad=date(2022, 3, 14), peso=2.0, fs=True),
    dict(id=117, nome="Carne Moída Plant-Based 400g", cat="Congelados", sub="Carne Moída", emb="Pouch", cont="400 g",
         temp="Congelado", shelf=365, ucx=12, preco=24.90, custo=16.20, cad=date(2021, 11, 8), peso=4.0),
    dict(id=118, nome="Almôndega Plant-Based 300g", cat="Congelados", sub="Almôndega", emb="Pouch", cont="300 g",
         temp="Congelado", shelf=365, ucx=12, preco=21.90, custo=14.10, cad=date(2022, 8, 1), peso=2.0),
    dict(id=119, nome="Frango Vegetal Empanado 300g", cat="Congelados", sub="Empanados", emb="Caixa", cont="300 g",
         temp="Congelado", shelf=365, ucx=12, preco=23.90, custo=15.30, lanc=date(2025, 2, 3), peso=3.0),
    dict(id=120, nome="Linguiça Plant-Based 300g", cat="Congelados", sub="Linguiça", emb="Bandeja", cont="300 g",
         temp="Congelado", shelf=365, ucx=12, preco=21.50, custo=13.80, cad=date(2022, 5, 2), desc=date(2026, 3, 31),
         subst=121, peso=2.0),
    dict(id=121, nome="Linguiça Plant-Based Toscana 300g", cat="Congelados", sub="Linguiça", emb="Bandeja", cont="300 g",
         temp="Congelado", shelf=365, ucx=12, preco=22.50, custo=14.20, lanc=date(2026, 2, 2), peso=2.2),
    dict(id=122, nome="Hambúrguer Plant-Based Smash 320g", cat="Congelados", sub="Hambúrguer", emb="Caixa", cont="4 x 80 g",
         temp="Congelado", shelf=365, ucx=12, preco=26.90, custo=17.60, lanc=date(2025, 10, 6), peso=2.5),
    # --- Sobremesas --------------------------------------------------------
    dict(id=104, nome="Sorvete Vegano Chocolate 473ml", cat="Sobremesas", sub="Sorvete Pote", emb="Pote", cont="473 ml",
         temp="Congelado", shelf=365, ucx=6, preco=34.90, custo=25.00, cad=date(2021, 11, 8), peso=2.5),
    dict(id=123, nome="Sorvete Vegano Baunilha 473ml", cat="Sobremesas", sub="Sorvete Pote", emb="Pote", cont="473 ml",
         temp="Congelado", shelf=365, ucx=6, preco=34.90, custo=25.00, cad=date(2022, 10, 3), peso=1.8),
    dict(id=124, nome="Sorvete Vegano Doce de Leite 473ml - Edição Verão", cat="Sobremesas", sub="Sorvete Pote", emb="Pote",
         cont="473 ml", temp="Congelado", shelf=365, ucx=6, preco=36.90, custo=26.00, cad=date(2023, 10, 2), peso=1.5,
         sazonal=True),
    dict(id=125, nome="Sorvete Vegano Chocolate 1,5L", cat="Sobremesas", sub="Sorvete Família", emb="Pote", cont="1,5 L",
         temp="Congelado", shelf=365, ucx=4, preco=69.90, custo=47.00, cad=date(2023, 3, 6), peso=1.2),
    # --- Refrigerados ------------------------------------------------------
    dict(id=126, nome="Queijo Vegetal Fatiado 150g", cat="Refrigerados", sub="Queijo Vegetal", emb="Bandeja", cont="150 g",
         temp="Refrigerado", shelf=60, ucx=20, preco=16.90, custo=10.80, cad=date(2022, 4, 4), peso=3.0),
    dict(id=127, nome="Queijo Vegetal Parmesão Ralado 100g", cat="Refrigerados", sub="Queijo Vegetal", emb="Pouch", cont="100 g",
         temp="Refrigerado", shelf=90, ucx=24, preco=14.90, custo=9.20, cad=date(2023, 2, 6), peso=1.8),
    dict(id=128, nome="Requeijão Vegetal 200g", cat="Refrigerados", sub="Requeijão", emb="Copo", cont="200 g",
         temp="Refrigerado", shelf=75, ucx=24, preco=13.90, custo=8.60, cad=date(2022, 7, 4), peso=2.5),
    dict(id=129, nome="Iogurte Vegetal Morango 170g", cat="Refrigerados", sub="Iogurte", emb="Copo", cont="170 g",
         temp="Refrigerado", shelf=35, ucx=24, preco=6.90, custo=4.10, cad=date(2023, 5, 8), peso=2.5),
    dict(id=130, nome="Iogurte Vegetal Natural 500g", cat="Refrigerados", sub="Iogurte", emb="Pote", cont="500 g",
         temp="Refrigerado", shelf=35, ucx=12, preco=15.90, custo=9.80, lanc=date(2026, 4, 6), peso=1.5),
]
for _p in PRODUTOS:
    _p.setdefault("lanc", None)
    _p.setdefault("desc", None)
    _p.setdefault("subst", None)
    _p.setdefault("fs", False)
    _p.setdefault("sazonal", False)
    _p.setdefault("cad", _p["lanc"])
    _p["marca"] = {"Bebidas": "Verde Vivo", "Condimentos": "Verde Vivo", "Congelados": "Brasa Vegetal",
                   "Sobremesas": "Frescor Vegano", "Refrigerados": "Verde Vivo Fresh"}[_p["cat"]]
    if _p["fs"]:
        _p["marca"] += " Food Service"
PROD = {p["id"]: p for p in PRODUTOS}
SKUS = [p["id"] for p in PRODUTOS]
MESES_SAZONAL = {11, 12, 1, 2, 3}

UF_REGIAO = {"SP": "Sudeste", "RJ": "Sudeste", "MG": "Sudeste", "ES": "Sudeste",
             "PR": "Sul", "SC": "Sul", "RS": "Sul",
             "DF": "Centro-Oeste", "GO": "Centro-Oeste",
             "PE": "Nordeste", "BA": "Nordeste", "CE": "Nordeste",
             "AM": "Norte", "PA": "Norte"}
LEAD_TIME_UF = {"SP": 1, "RJ": 2, "MG": 2, "ES": 3, "PR": 3, "SC": 3, "RS": 4, "DF": 3, "GO": 3,
                "PE": 1, "BA": 2, "CE": 3, "AM": 9, "PA": 6}

# pot = potencial de compra em unidades/mês na base de jan/2024
# freq: S = semanal | 2S = duas vezes por semana | Q = quinzenal
_C = [
    # ID, Nome, Grupo, Canal, Subcanal, UF, Cidade, Porte, pot, freq, executivo, inicio, inativação
    ("C001", "Horizonte Supermercados - CD São Paulo", "Grupo Horizonte", "Varejo Alimentar", "Supermercado", "SP", "São Paulo", "Grande", 32000, "S", "Ana Souza", date(2021, 5, 3), None),
    ("C002", "Horizonte Supermercados - CD Rio de Janeiro", "Grupo Horizonte", "Varejo Alimentar", "Supermercado", "RJ", "Rio de Janeiro", "Grande", 18000, "S", "Bruno Lima", date(2021, 9, 1), None),
    ("C003", "Horizonte Supermercados - CD Belo Horizonte", "Grupo Horizonte", "Varejo Alimentar", "Supermercado", "MG", "Contagem", "Médio", 9000, "S", "Bruno Lima", date(2022, 2, 7), None),
    ("C004", "Horizonte Express - CD São Paulo", "Grupo Horizonte", "Varejo Alimentar", "Proximidade", "SP", "São Paulo", "Médio", 6000, "2S", "Ana Souza", date(2022, 6, 1), None),
    ("C005", "Vale Verde Supermercados - CD Curitiba", "Grupo Vale Verde", "Varejo Alimentar", "Supermercado", "PR", "São José dos Pinhais", "Grande", 15000, "S", "Carla Mendes", date(2021, 7, 5), None),
    ("C006", "Vale Verde Supermercados - CD Porto Alegre", "Grupo Vale Verde", "Varejo Alimentar", "Supermercado", "RS", "Gravataí", "Médio", 9000, "S", "Carla Mendes", date(2022, 3, 1), None),
    ("C007", "Vale Verde Supermercados - CD Joinville", "Grupo Vale Verde", "Varejo Alimentar", "Supermercado", "SC", "Joinville", "Médio", 5000, "Q", "Carla Mendes", date(2023, 4, 3), None),
    ("C008", "Rede Primavera - Ribeirão Preto", "Rede Primavera", "Varejo Alimentar", "Supermercado Regional", "SP", "Ribeirão Preto", "Médio", 5500, "S", "Ana Souza", date(2022, 1, 10), None),
    ("C009", "Rede Primavera - Campinas", "Rede Primavera", "Varejo Alimentar", "Supermercado Regional", "SP", "Campinas", "Médio", 6000, "S", "Ana Souza", date(2022, 1, 10), None),
    ("C010", "Supermercados Bom Sabor - CD Recife", "Grupo Bom Sabor", "Varejo Alimentar", "Supermercado", "PE", "Recife", "Médio", 7000, "S", "Diego Rocha", date(2022, 8, 1), None),
    ("C011", "Supermercados Bom Sabor - CD Salvador", "Grupo Bom Sabor", "Varejo Alimentar", "Supermercado", "BA", "Salvador", "Médio", 6000, "S", "Diego Rocha", date(2022, 8, 1), None),
    ("C012", "Supermercados Bom Sabor - CD Fortaleza", "Grupo Bom Sabor", "Varejo Alimentar", "Supermercado", "CE", "Fortaleza", "Pequeno", 3500, "Q", "Diego Rocha", date(2023, 6, 5), None),
    ("C013", "Mercado Estrela do Cerrado - Brasília", "Rede Estrela do Cerrado", "Varejo Alimentar", "Supermercado Regional", "DF", "Brasília", "Médio", 6500, "S", "Bruno Lima", date(2022, 4, 4), None),
    ("C014", "Mercado Estrela do Cerrado - Goiânia", "Rede Estrela do Cerrado", "Varejo Alimentar", "Supermercado Regional", "GO", "Goiânia", "Pequeno", 3000, "Q", "Bruno Lima", date(2023, 2, 1), None),
    ("C015", "Hiper Família - São Bernardo do Campo", "Hiper Família", "Varejo Alimentar", "Hipermercado", "SP", "São Bernardo do Campo", "Médio", 7500, "S", "Ana Souza", date(2021, 10, 4), None),
    ("C016", "Empório Natural Mix - São Paulo", "Empório Natural Mix", "Varejo Alimentar", "Loja Especializada", "SP", "São Paulo", "Pequeno", 3200, "S", "Ana Souza", date(2021, 4, 5), None),
    ("C017", "Empório Natural Mix - Rio de Janeiro", "Empório Natural Mix", "Varejo Alimentar", "Loja Especializada", "RJ", "Rio de Janeiro", "Pequeno", 2200, "Q", "Bruno Lima", date(2022, 11, 7), None),
    ("C018", "Max Economia Atacarejo - CD Osasco", "Grupo Max Economia", "Atacarejo", "Atacarejo", "SP", "Osasco", "Grande", 30000, "2S", "Ana Souza", date(2021, 6, 1), None),
    ("C019", "Max Economia Atacarejo - CD Duque de Caxias", "Grupo Max Economia", "Atacarejo", "Atacarejo", "RJ", "Duque de Caxias", "Grande", 16000, "S", "Bruno Lima", date(2021, 11, 1), None),
    ("C020", "Max Economia Atacarejo - CD Betim", "Grupo Max Economia", "Atacarejo", "Atacarejo", "MG", "Betim", "Médio", 9000, "S", "Bruno Lima", date(2022, 5, 2), None),
    ("C021", "Max Economia Atacarejo - CD Cabo de Santo Agostinho", "Grupo Max Economia", "Atacarejo", "Atacarejo", "PE", "Cabo de Santo Agostinho", "Médio", 8000, "S", "Diego Rocha", date(2023, 3, 1), None),
    ("C022", "Max Economia Atacarejo - CD Camaçari", "Grupo Max Economia", "Atacarejo", "Atacarejo", "BA", "Camaçari", "Médio", 7000, "S", "Diego Rocha", date(2026, 3, 2), None),
    ("C023", "Atacado Ponto Forte - CD Curitiba", "Grupo Ponto Forte", "Atacarejo", "Atacarejo", "PR", "Curitiba", "Médio", 8000, "S", "Carla Mendes", date(2022, 9, 5), None),
    ("C024", "Atacado Ponto Forte - CD Goiânia", "Grupo Ponto Forte", "Atacarejo", "Atacarejo", "GO", "Aparecida de Goiânia", "Médio", 6000, "S", "Bruno Lima", date(2023, 1, 9), None),
    ("C025", "Atacado Ponto Forte - CD Fortaleza", "Grupo Ponto Forte", "Atacarejo", "Atacarejo", "CE", "Maracanaú", "Pequeno", 4000, "Q", "Diego Rocha", date(2023, 8, 7), None),
    ("C026", "Distribuidora Aliança Nordeste", "Distribuidora Aliança Nordeste", "Distribuidor", "Distribuidor Alimentar", "PE", "Jaboatão dos Guararapes", "Grande", 22000, "S", "Elisa Prado", date(2021, 8, 2), None),
    ("C027", "Distribuidora Sertão Alimentos", "Distribuidora Sertão Alimentos", "Distribuidor", "Distribuidor Alimentar", "BA", "Feira de Santana", "Médio", 9000, "S", "Elisa Prado", date(2022, 4, 4), None),
    ("C028", "Distribuidora Sul Frios", "Distribuidora Sul Frios", "Distribuidor", "Distribuidor Alimentar", "RS", "Canoas", "Médio", 10000, "S", "Elisa Prado", date(2021, 12, 6), None),
    ("C029", "Distribuidora Planalto Central", "Distribuidora Planalto Central", "Distribuidor", "Distribuidor Alimentar", "GO", "Anápolis", "Médio", 8000, "Q", "Elisa Prado", date(2022, 7, 4), None),
    ("C030", "Distribuidora Norte Frio", "Distribuidora Norte Frio", "Distribuidor", "Distribuidor Alimentar", "AM", "Manaus", "Médio", 7000, "Q", "Elisa Prado", date(2022, 10, 3), None),
    ("C031", "Distribuidora Pará Food", "Distribuidora Pará Food", "Distribuidor", "Distribuidor Alimentar", "PA", "Ananindeua", "Pequeno", 4500, "Q", "Elisa Prado", date(2023, 5, 2), None),
    ("C032", "Distribuidora Vale do Paraíba", "Distribuidora Vale do Paraíba", "Distribuidor", "Distribuidor Alimentar", "SP", "São José dos Campos", "Médio", 9000, "S", "Elisa Prado", date(2021, 9, 6), None),
    ("C033", "Distribuidora Minas Frios", "Distribuidora Minas Frios", "Distribuidor", "Distribuidor Alimentar", "MG", "Contagem", "Grande", 14000, "S", "Elisa Prado", date(2021, 7, 5), None),
    ("C034", "Distribuidora Litoral Capixaba", "Distribuidora Litoral Capixaba", "Distribuidor", "Distribuidor Alimentar", "ES", "Serra", "Pequeno", 4000, "Q", "Elisa Prado", date(2025, 7, 1), None),
    ("C035", "Distribuidora Campos Gerais", "Distribuidora Campos Gerais", "Distribuidor", "Distribuidor Alimentar", "PR", "Ponta Grossa", "Pequeno", 4500, "Q", "Elisa Prado", date(2022, 2, 7), date(2025, 10, 31)),
    ("C036", "Distribuidora Serra Gaúcha", "Distribuidora Serra Gaúcha", "Distribuidor", "Distribuidor Food Service", "RS", "Caxias do Sul", "Pequeno", 3500, "Q", "Elisa Prado", date(2023, 3, 6), None),
    ("C037", "Burger Station - CD São Paulo", "Burger Station", "Food Service", "Rede de Fast Food", "SP", "Barueri", "Médio", 9000, "S", "Fábio Nunes", date(2022, 5, 2), None),
    ("C038", "Burger Station - CD Rio de Janeiro", "Burger Station", "Food Service", "Rede de Fast Food", "RJ", "Rio de Janeiro", "Pequeno", 4000, "S", "Fábio Nunes", date(2023, 2, 6), None),
    ("C039", "Cantina Raiz Restaurantes", "Cantina Raiz", "Food Service", "Restaurantes", "SP", "São Paulo", "Pequeno", 2500, "S", "Fábio Nunes", date(2022, 9, 5), None),
    ("C040", "Café Grão Nobre - CD São Paulo", "Café Grão Nobre", "Food Service", "Cafeterias", "SP", "São Paulo", "Pequeno", 3500, "S", "Fábio Nunes", date(2022, 7, 4), None),
    ("C041", "Café Grão Nobre - CD Curitiba", "Café Grão Nobre", "Food Service", "Cafeterias", "PR", "Curitiba", "Pequeno", 1500, "Q", "Fábio Nunes", date(2023, 9, 4), None),
    ("C042", "Nutrir Cozinhas Industriais", "Nutrir Cozinhas Industriais", "Food Service", "Cozinha Industrial", "SP", "Guarulhos", "Pequeno", 3000, "S", "Fábio Nunes", date(2023, 1, 9), None),
    ("C043", "Hotelaria Atlântico", "Hotelaria Atlântico", "Food Service", "Hotelaria", "RJ", "Rio de Janeiro", "Pequeno", 1200, "Q", "Fábio Nunes", date(2023, 6, 5), None),
    ("C044", "Vida Leve Loja Online", "Vida Leve", "E-commerce", "Loja Online", "SP", "São Paulo", "Pequeno", 2500, "2S", "Fábio Nunes", date(2022, 3, 7), None),
    ("C045", "Cesta Digital Marketplace", "Cesta Digital", "E-commerce", "Marketplace", "SP", "Barueri", "Médio", 5000, "2S", "Fábio Nunes", date(2022, 10, 3), None),
    ("C046", "Já Chegou Quick Commerce - SP", "Já Chegou", "E-commerce", "Quick Commerce", "SP", "São Paulo", "Pequeno", 3000, "2S", "Fábio Nunes", date(2025, 7, 1), None),
    ("C047", "Já Chegou Quick Commerce - RJ", "Já Chegou", "E-commerce", "Quick Commerce", "RJ", "Rio de Janeiro", "Pequeno", 1800, "2S", "Fábio Nunes", date(2025, 9, 1), None),
]
CLIENTES = []
for (cid, nome, grupo, canal, sub, uf, cidade, porte, pot, freq, execu, ini, inat) in _C:
    CLIENTES.append(dict(
        id=cid, nome=nome, grupo=grupo, canal=canal, sub=sub, uf=uf, cidade=cidade, porte=porte, pot=pot,
        freq=freq, exec=execu, ini=ini, inat=inat, regiao=UF_REGIAO[uf],
        cd="CD02" if UF_REGIAO[uf] in ("Nordeste", "Norte") else "CD01",
        tipo="Indireto" if canal == "Distribuidor" else "Direto",
        desc_contrato=round(float(rng.uniform(0, 0.04)), 3),
        dia_semana=int(rng.integers(0, 5)) if freq != "2S" else int(rng.integers(0, 2)),
        paridade=int(rng.integers(0, 2)),
    ))
CLI = {c["id"]: c for c in CLIENTES}
CANAIS = ["Varejo Alimentar", "Atacarejo", "Distribuidor", "Food Service", "E-commerce"]

DESC_CANAL = {"Varejo Alimentar": 0.0, "Atacarejo": 0.07, "Distribuidor": 0.15, "Food Service": 0.05, "E-commerce": 0.03}
CV_PORTE = {"Grande": 0.25, "Médio": 0.40, "Pequeno": 0.60}

# Mix de Food Service por subcanal (peso relativo de cada SKU)
MIX_FS = {
    "Rede de Fast Food": {116: 8, 103: 2, 122: 2, 113: 4, 114: 3, 119: 2},
    "Restaurantes": {117: 4, 116: 3, 113: 3, 118: 2, 102: 1, 101: 1, 120: 1, 121: 1},
    "Cafeterias": {107: 10, 101: 3, 105: 2, 108: 1},
    "Cozinha Industrial": {117: 5, 116: 4, 113: 3, 118: 2, 120: 2, 121: 2},
    "Hotelaria": {101: 3, 107: 2, 105: 2, 113: 1, 114: 1, 104: 1, 126: 1},
}
AJUSTE_ATACAREJO = {101: 1.4, 102: 1.3, 103: 1.2, 108: 1.3}
AJUSTE_ECOM = {105: 1.5, 107: 1.3, 104: 1.2, 125: 1.3}
CANIBALIZACAO = {109: [(108, 0.10)], 115: [(112, 0.15), (111, 0.04)], 122: [(103, 0.07)], 130: [(129, 0.05)]}

SAZONALIDADE = {  # índice mensal por categoria (jan..dez) - jan inclui o efeito "Veganuary"
    "Bebidas":      [1.08, 1.00, 1.00, 0.97, 0.97, 1.01, 1.04, 1.01, 0.97, 0.97, 0.97, 1.01],
    "Condimentos":  [1.06, 0.98, 0.97, 0.95, 0.95, 0.95, 0.97, 1.00, 1.00, 1.02, 1.05, 1.15],
    "Congelados":   [1.07, 0.95, 1.07, 1.08, 0.97, 0.94, 0.94, 0.98, 0.97, 0.99, 1.00, 1.04],
    "Sobremesas":   [1.45, 1.35, 1.15, 0.95, 0.80, 0.65, 0.65, 0.75, 0.90, 1.05, 1.20, 1.40],
    "Refrigerados": [1.06, 1.00, 1.00, 1.00, 0.98, 0.97, 0.97, 0.98, 1.00, 1.00, 1.02, 1.07],
}
for _k, _v in SAZONALIDADE.items():
    _m = sum(_v) / 12
    SAZONALIDADE[_k] = [x / _m for x in _v]


# =============================================================================
# SORTIMENTO E DEMANDA "VERDADEIRA" (ESPERADA) POR CLIENTE x SKU x MÊS
# =============================================================================

def afinidade(cli: dict, prod: dict) -> float:
    canal = cli["canal"]
    if canal == "Food Service":
        return float(MIX_FS[cli["sub"]].get(prod["id"], 0.0))
    if prod["fs"]:
        return 0.8 if canal == "Distribuidor" else 0.0
    refrig = prod["cat"] == "Refrigerados"
    if refrig and cli["cd"] == "CD02":  # cadeia fria de vida curta não vai para N/NE
        return 0.0
    if canal == "Atacarejo":
        if refrig or (prod["peso"] < 2.5 and prod["id"] not in (108, 109)):
            return 0.0
        return prod["peso"] * AJUSTE_ATACAREJO.get(prod["id"], 1.0)
    if canal == "E-commerce":
        return prod["peso"] * AJUSTE_ECOM.get(prod["id"], 1.0)
    return prod["peso"]


def montar_sortimento() -> dict[tuple[str, int], dict]:
    """Define quais SKUs cada cliente compra, com peso e data de listagem."""
    sort = {}
    for c in CLIENTES:
        candidatos = [(p, afinidade(c, p)) for p in PRODUTOS]
        candidatos = [(p, a) for p, a in candidatos if a > 0]
        if c["porte"] == "Pequeno" and c["canal"] in ("Varejo Alimentar", "Distribuidor", "Atacarejo"):
            candidatos.sort(key=lambda x: -x[1])
            candidatos = candidatos[:14]
        inicio_cli = max(c["ini"], INICIO_VENDAS)
        for p, a in candidatos:
            if p["lanc"]:
                prob = {"Grande": 0.95, "Médio": 0.85, "Pequeno": 0.5}[c["porte"]]
                if rng.random() > prob:
                    continue
                atraso = {"Grande": (0, 25), "Médio": (7, 50), "Pequeno": (15, 90)}[c["porte"]]
                listagem = max(p["lanc"], inicio_cli) + timedelta(days=int(rng.integers(*atraso)))
            else:
                listagem = inicio_cli
            sort[(c["id"], p["id"])] = dict(peso=a * float(rng.lognormal(0, 0.35)), listagem=listagem)
    # participação de cada SKU no potencial do cliente (base: SKUs já existentes)
    for c in CLIENTES:
        chaves = [k for k in sort if k[0] == c["id"]]
        base = sum(sort[k]["peso"] for k in chaves if not PROD[k[1]]["lanc"]) or 1.0
        for k in chaves:
            sort[k]["share"] = sort[k]["peso"] / base
    return sort


def fator_crescimento(m: int) -> float:
    g = 1.0
    for i in range(1, m + 1):
        ano = mes_data(i).year
        g *= 1 + {2024: 0.014, 2025: 0.009}.get(ano, 0.005)
    return g


def fator_ciclo_vida(p: dict, m: int) -> float:
    f = 1.0
    if p["lanc"]:
        lm = mes_idx(p["lanc"])
        if m < lm:
            return 0.0
        f *= 1 - math.exp(-(m - lm + 0.6) / 2.2)
    if p["desc"]:
        dm = mes_idx(p["desc"])
        if m > dm:
            return 0.0
        f *= {dm - 1: 0.8, dm: 0.5}.get(m, 1.0)
    if p["sazonal"] and mes_data(m).month not in MESES_SAZONAL:
        return 0.0
    for lancado, vitimas in CANIBALIZACAO.items():
        for vit, pct in vitimas:
            if vit == p["id"]:
                f *= 1 - pct * fator_ciclo_vida(PROD[lancado], m)
    return f


def fator_preco_mercado(canal: str, cat: str, m: int) -> float:
    """Aumentos de preço (mar/2025 e mar/2026) com compra antecipada e
    entrada de concorrente em Bebidas a partir de abr/2026."""
    f = 1.0
    antecipa = canal in ("Distribuidor", "Atacarejo")
    efeitos = {
        13: 1.15 if antecipa else 1.03, 14: 0.88 if antecipa else 0.95, 15: 0.96 if antecipa else 0.98,
        25: 1.10 if antecipa else 1.02, 26: 0.92 if antecipa else 0.97,
    }
    f *= efeitos.get(m, 1.0)
    if cat == "Bebidas":
        f *= {27: 0.96, 28: 0.93}.get(m, 0.91 if m >= 29 else 1.0)
    return f


def fator_cliente(c: dict, m: int) -> float:
    im = mes_idx(c["ini"]) if c["ini"] >= INICIO_VENDAS else -99
    if m < im:
        return 0.0
    f = {0: 0.55, 1: 0.8, 2: 0.95}.get(m - im, 1.0)
    if c["inat"]:
        xm = mes_idx(c["inat"])
        if m > xm:
            return 0.0
        f *= {xm - 1: 0.8, xm: 0.5}.get(m, 1.0)
    return f


def montar_demanda_esperada(sort: dict) -> dict[tuple[str, int], np.ndarray]:
    G = np.array([fator_crescimento(m) for m in range(N_MESES_TOTAL)])
    # choque comum do SKU no mês (mídia, ruptura no varejo, clima...) que afeta todos os clientes
    choque_sku = {}
    for sku in SKUS:
        nivel, arr = 0.0, np.ones(N_MESES_TOTAL)
        for m in range(N_MESES_TOTAL):
            nivel = 0.5 * nivel + rng.normal(0, 0.11)
            arr[m] = math.exp(nivel)
        choque_sku[sku] = arr
    E = {}
    for (cid, sku), info in sort.items():
        c, p = CLI[cid], PROD[sku]
        rw = np.ones(N_MESES_TOTAL)
        nivel = 0.0
        for m in range(N_MESES_TOTAL):
            nivel = 0.85 * nivel + rng.normal(0, 0.10)
            rw[m] = math.exp(nivel)
        arr = np.zeros(N_MESES_TOTAL)
        for m in range(N_MESES_TOTAL):
            arr[m] = (c["pot"] * info["share"] * G[m] * SAZONALIDADE[p["cat"]][mes_data(m).month - 1]
                      * fator_ciclo_vida(p, m) * fator_preco_mercado(c["canal"], p["cat"], m)
                      * fator_cliente(c, m) * rw[m] * choque_sku[sku][m])
        E[(cid, sku)] = arr
    return E


# =============================================================================
# PROMOÇÕES
# =============================================================================

MECANICAS = [("Desconto em tabela", 0.10, 0.18), ("Encarte/Tabloide", 0.12, 0.22),
             ("Ponta de gôndola", 0.05, 0.12), ("Leve 3 Pague 2", 0.30, 0.34)]


def gerar_promocoes(sort: dict):
    promos = []        # linhas da tabela f_Promocoes
    por_chave = defaultdict(list)
    seq = 1

    def adicionar(pid, cid, sku, mec, cad, ini, fim, desc, uplift, bonif, status):
        real = uplift * float(rng.lognormal(0, 0.35))  # o uplift real nunca é o planejado
        reg = dict(ID_Promocao=pid, ID_Cliente=cid, ID_Produto=sku, Mecanica=mec, Data_Cadastro=cad,
                   Data_Inicio=ini, Data_Fim=fim, Desconto_Pct=round(desc * 100, 1),
                   Uplift_Planejado_Pct=round(uplift * 100, 1), Bonificacao_Pct=round(bonif * 100, 1),
                   Status=status)
        promos.append(reg)
        por_chave[(cid, sku)].append(dict(ini=ini, fim=fim, desc=desc, uplift_real=real, uplift_plan=uplift,
                                          bonif=bonif, id=pid, cancelada=status == "Cancelada", cad=cad))

    def skus_ativos(cid, d):
        out = []
        for (c2, sku), info in sort.items():
            p = PROD[sku]
            if c2 != cid or info["listagem"] > d or (p["desc"] and d > p["desc"] - timedelta(days=45)):
                continue
            if p["sazonal"] and d.month not in MESES_SAZONAL:
                continue
            out.append((sku, info["peso"]))
        return out

    # 1) Ações táticas por cliente
    for c in CLIENTES:
        if c["canal"] == "Food Service":
            continue
        gap = (90, 150) if c["canal"] == "Distribuidor" else (35, 80)
        d = max(c["ini"], INICIO_VENDAS) + timedelta(days=int(rng.integers(5, 40)))
        fim_cli = c["inat"] or FIM_VENDAS
        while d < fim_cli - timedelta(days=20):
            ativos = skus_ativos(c["id"], d)
            if ativos:
                pesos = np.array([w for _, w in ativos])
                n = min(len(ativos), int(rng.integers(1, 4)))
                escolhidos = rng.choice([s for s, _ in ativos], size=n, replace=False, p=pesos / pesos.sum())
                if c["canal"] == "Distribuidor":
                    mec, dmin, dmax = ("Ação de sell-out (verba)", 0.05, 0.10)
                else:
                    mec, dmin, dmax = MECANICAS[int(rng.integers(0, len(MECANICAS)))]
                ini = proximo_dia_util(d)
                dur = int(rng.integers(7, 22))
                fim = ini + timedelta(days=dur)
                cad = ini - timedelta(days=int(rng.integers(10, 75)))
                status = "Cancelada" if rng.random() < 0.06 else "Executada"
                pid = f"PR{seq:05d}"
                seq += 1
                for sku in escolhidos:
                    desc = float(rng.uniform(dmin, dmax))
                    uplift = max(0.15, 3.2 * desc + float(rng.normal(0, 0.12)))
                    if c["canal"] == "Distribuidor":
                        uplift *= 0.6
                    bonif = 0.04 if mec == "Encarte/Tabloide" else 0.0   # contrapartida do encarte
                    adicionar(pid, c["id"], int(sku), mec, cad, ini, fim, desc, uplift, bonif, status)
            d += timedelta(days=int(rng.integers(*gap)))

    # 2) Aniversário das redes (todo ano no mesmo mês, todos os CDs do grupo, com bonificação)
    grupos = defaultdict(list)
    for c in CLIENTES:
        if c["canal"] in ("Varejo Alimentar", "Atacarejo"):
            grupos[c["grupo"]].append(c)
    for grupo, membros in grupos.items():
        mes_aniv = int(rng.integers(3, 11))
        for ano in (2024, 2025, 2026):
            ini = proximo_dia_util(date(ano, mes_aniv, 1) + timedelta(days=int(rng.integers(0, 10))))
            if ini > FIM_VENDAS - timedelta(days=20):
                continue
            fim = ini + timedelta(days=14)
            cad = ini - timedelta(days=int(rng.integers(45, 90)))
            pid = f"PR{seq:05d}"
            seq += 1
            for c in membros:
                if c["ini"] > ini or (c["inat"] and c["inat"] < fim):
                    continue
                ativos = sorted(skus_ativos(c["id"], ini), key=lambda x: -x[1])[: int(rng.integers(3, 7))]
                for sku, _ in ativos:
                    adicionar(pid, c["id"], sku, "Aniversário da rede", cad, ini, fim, 0.15, 0.8, 0.08, "Executada")

    # 3) Black Friday no e-commerce
    for ano in (2024, 2025):
        bf = n_esimo_dia_semana(ano, 11, 3, 4) + timedelta(days=1)
        ini, fim = bf - timedelta(days=4), bf + timedelta(days=3)
        pid = f"PR{seq:05d}"
        seq += 1
        for c in CLIENTES:
            if c["canal"] != "E-commerce" or c["ini"] > ini:
                continue
            for sku, _ in sorted(skus_ativos(c["id"], ini), key=lambda x: -x[1])[:6]:
                adicionar(pid, c["id"], sku, "Black Friday", ini - timedelta(days=40), ini, fim, 0.20, 1.2, 0.0, "Executada")
    return promos, por_chave


# =============================================================================
# PEDIDOS (DEMANDA REAL DOS CLIENTES)
# =============================================================================

def preco_lista_na_data(p: dict, d: date) -> float:
    """O d_Produto guarda o preço ATUAL. Antes dos reajustes o preço era menor."""
    reaj_2026 = 1.04 if p["cat"] == "Bebidas" else 1.06
    preco = p["preco"]
    if d < date(2026, 3, 1):
        preco /= reaj_2026
    if d < date(2025, 3, 1):
        preco /= 1.07
    return round(preco, 2)


def datas_de_pedido(c: dict) -> list[date]:
    ini = max(c["ini"], INICIO_VENDAS)
    fim = min(c["inat"] or FIM_VENDAS, FIM_VENDAS)
    dias = []
    segunda = ini - timedelta(days=ini.weekday())
    while segunda <= fim:
        if c["freq"] == "S":
            alvos = [c["dia_semana"]]
        elif c["freq"] == "2S":
            alvos = [c["dia_semana"], c["dia_semana"] + 3]
        else:
            alvos = [c["dia_semana"]] if segunda.isocalendar()[1] % 2 == c["paridade"] else []
        for a in alvos:
            d = proximo_dia_util(segunda + timedelta(days=a))
            if ini <= d <= fim and (not dias or d > dias[-1]):
                dias.append(d)
        segunda += timedelta(days=7)
    return dias


def efeito_promocional(lista_promos: list, d: date):
    mult, pid, desc, bonif = 1.0, "", 0.0, 0.0
    for pr in lista_promos:
        if pr["cancelada"]:
            continue
        if pr["ini"] <= d <= pr["fim"]:
            mult *= 1 + pr["uplift_real"]
            pid, desc, bonif = pr["id"], pr["desc"], pr["bonif"]
        elif pr["ini"] - timedelta(days=7) <= d < pr["ini"]:
            mult *= 1.15   # abastecimento das lojas antes da ação
        elif pr["fim"] < d <= pr["fim"] + timedelta(days=14):
            mult *= 0.82   # ressaca pós-promoção
    return mult, pid, desc, bonif


def gerar_pedidos(sort: dict, E: dict, promos_chave: dict) -> list[dict]:
    linhas = []
    seq_pedido = 1
    skus_cli = defaultdict(list)
    for (cid, sku) in sort:
        skus_cli[cid].append(sku)
    for c in CLIENTES:
        datas = datas_de_pedido(c)
        n_por_mes = defaultdict(int)
        for d in datas:
            n_por_mes[mes_idx(d)] += 1
        ja_comprou = set()
        k_gamma = 1 / CV_PORTE[c["porte"]] ** 2
        for d in datas:
            fat = proximo_dia_util(d, estritamente_depois=True)   # faturamento D+1 útil
            if fat > FIM_VENDAS:
                continue
            m = mes_idx(d)
            pedido = f"PV{seq_pedido:07d}"
            seq_pedido += 1
            bloqueio = c["canal"] == "Distribuidor" and rng.random() < 0.012
            for sku in skus_cli[c["id"]]:
                p = PROD[sku]
                info = sort[(c["id"], sku)]
                if d < info["listagem"] or (p["desc"] and d > p["desc"]):
                    continue
                if p["sazonal"] and d.month not in MESES_SAZONAL:
                    continue
                media = E[(c["id"], sku)][m] / n_por_mes[m]
                mult, pid, desc_promo, bonif = efeito_promocional(promos_chave.get((c["id"], sku), []), d)
                primeira = sku not in ja_comprou
                if primeira and p["lanc"]:
                    mult *= 2.5      # carga inicial (pipeline fill) do lançamento
                lam = media * mult * rng.gamma(k_gamma, 1 / k_gamma) / p["ucx"]
                cx = int(rng.poisson(lam))
                if cx <= 0:
                    continue
                ja_comprou.add(sku)
                base = dict(ID_Pedido=pedido, Data_Pedido=d, Data=fat, ID_Cliente=c["id"], ID_Produto=sku,
                            ID_CD=c["cd"], Preco_Unitario_Lista=preco_lista_na_data(p, fat),
                            Desconto_Comercial_Pct=round((DESC_CANAL[c["canal"]] + c["desc_contrato"]) * 100, 1),
                            Desconto_Promocional_Pct=round(desc_promo * 100, 1), ID_Promocao=pid,
                            corte_previo=0, motivo_previo="")
                if bloqueio:
                    base["corte_previo"], base["motivo_previo"] = cx * p["ucx"], "Bloqueio de crédito"
                elif p["temp"] == "Refrigerado" and rng.random() < 0.02:
                    base["corte_previo"] = int(math.ceil(cx * rng.uniform(0.3, 1.0))) * p["ucx"]
                    base["motivo_previo"] = "Shelf-life abaixo do exigido pelo cliente"
                linhas.append({**base, "Tipo_Movimento": "Venda", "Qtd_Pedida": cx * p["ucx"]})
                # bonificação: introdução de lançamento (10%) ou campanha com bonificação
                pct_bonif = 0.10 if (primeira and p["lanc"]) else bonif
                if pct_bonif > 0:
                    bcx = max(1, int(round(cx * pct_bonif)))
                    linhas.append({**base, "Tipo_Movimento": "Bonificação", "Qtd_Pedida": bcx * p["ucx"],
                                   "Desconto_Comercial_Pct": 0.0, "Desconto_Promocional_Pct": 0.0,
                                   "corte_previo": bcx * p["ucx"] if bloqueio else 0,
                                   "motivo_previo": "Bloqueio de crédito" if bloqueio else ""})
    return linhas


# =============================================================================
# FORECAST (ESTATÍSTICO, COMERCIAL, CONSENSO), PRODUÇÃO E ESTOQUE
# =============================================================================

class Simulador:
    def __init__(self, sort, E, promos, promos_chave, linhas):
        self.sort, self.E, self.promos, self.promos_chave = sort, E, promos, promos_chave
        self.linhas = linhas
        self.fat_sc = defaultdict(lambda: np.zeros(N_MESES_TOTAL))   # SKU x canal
        self.fat_cs = defaultdict(lambda: np.zeros(N_MESES_TOTAL))   # cliente x SKU
        self.fat_cat = defaultdict(lambda: np.zeros(N_MESES_TOTAL))  # categoria
        self.fat_cd = defaultdict(lambda: np.zeros(N_MESES_TOTAL))   # SKU x CD
        self.ped_sc = defaultdict(lambda: np.zeros(N_MESES_TOTAL))   # pedido (demanda) SKU x canal
        self.fc = {}                       # (ciclo, alvo, sku, canal, versao) -> qtd
        self.forecast_rows = []
        self.budget_rows = []
        self.estoque_rows = []
        self.estoque = defaultdict(float)  # (cd, sku) -> unidades
        self.canal_skus = defaultdict(set)
        for (cid, sku) in sort:
            self.canal_skus[CLI[cid]["canal"]].add(sku)
        self.cache_saz = {}
        # agregados da demanda esperada e índice de promoções (evita varreduras repetidas)
        self.E_sku = defaultdict(lambda: np.zeros(N_MESES_TOTAL))
        self.E_sku_cd = defaultdict(lambda: np.zeros(N_MESES_TOTAL))
        self.E_sku_canal = defaultdict(lambda: np.zeros(N_MESES_TOTAL))
        for (cid, sku), arr in E.items():
            self.E_sku[sku] += arr
            self.E_sku_cd[(sku, CLI[cid]["cd"])] += arr
            self.E_sku_canal[(sku, CLI[cid]["canal"])] += arr
        self.promos_idx = defaultdict(list)
        for (cid, sku), lista in promos_chave.items():
            for pr in lista:
                self.promos_idx[(sku, CLI[cid]["canal"])].append((cid, pr))
        # estoque inicial ~ 1 mês de demanda esperada
        for (cid, sku), arr in E.items():
            self.estoque[(CLI[cid]["cd"], sku)] += arr[0] * 1.0
        for k in list(self.estoque):
            self.estoque[k] = float(round(self.estoque[k] / PROD[k[1]]["ucx"]) * PROD[k[1]]["ucx"])
        self.linhas_por_mes = defaultdict(list)
        for ln in linhas:
            self.linhas_por_mes[mes_idx(ln["Data"])].append(ln)

    # ---------- índices sazonais estimados a partir do histórico ----------
    def indice_sazonal(self, cat: str, C: int) -> np.ndarray:
        chave = (cat, C)
        if chave in self.cache_saz:
            return self.cache_saz[chave]
        h = self.fat_cat[cat][:C]
        idx = np.ones(12)
        if C >= 13 and h.min() > 0:
            t = np.arange(C)
            coef = np.polyfit(t, np.log(h), 1)
            resid = h / np.exp(np.polyval(coef, t))
            for mes in range(12):
                vals = [resid[i] for i in range(C) if i % 12 == mes]
                if vals:
                    idx[mes] = np.mean(vals)
            idx = idx / idx.mean()
            idx = 1 + 0.8 * (idx - 1)   # amortece o ruído
        self.cache_saz[chave] = idx
        return idx

    def estatistico(self, sku: int, canal: str, C: int, T: int, usar_tendencia: bool = True) -> float:
        p = PROD[sku]
        if p["sazonal"] and mes_data(T).month not in MESES_SAZONAL:
            return 0.0
        h = self.fat_sc[(sku, canal)][:C]
        nz = np.nonzero(h)[0]
        if len(nz) == 0:
            return 0.0
        S = self.indice_sazonal(p["cat"], C)
        meses = np.arange(nz[0], C)
        if p["sazonal"]:
            meses = np.array([i for i in meses if h[i] > 0])
        d = h[meses] / S[meses % 12]
        ult = d[-3:]
        pesos = np.array([0.2, 0.3, 0.5])[-len(ult):]
        nivel = float((ult * pesos).sum() / pesos.sum())
        g = 0.0
        if usar_tendencia and len(d) >= 9 and not p["sazonal"]:
            ant = d[-9:-6].mean()
            if ant > 0:
                g = float(np.clip((d[-3:].mean() / ant) ** (1 / 6) - 1, -0.03, 0.03))
        return max(0.0, nivel * (1 + g) ** (T - (C - 1)) * S[T % 12])

    def promo_conhecida(self, sku: int, canal: str, C: int, T: int) -> float:
        data_ciclo = mes_data(C)
        ini_T, fim_T = mes_data(T), fim_mes(T)
        dias_T = (fim_T - ini_T).days + 1
        extra = 0.0
        for cid, pr in self.promos_idx.get((sku, canal), []):
            if True:
                if pr["cad"] >= data_ciclo or pr["fim"] < ini_T or pr["ini"] > fim_T:
                    continue
                if pr["cancelada"] and pr["ini"] - timedelta(days=7) < data_ciclo:
                    continue   # cancelamento já era conhecido no ciclo
                sobre = (min(pr["fim"], fim_T) - max(pr["ini"], ini_T)).days + 1
                h = self.fat_cs[(cid, sku)][max(0, C - 3):C]
                base = h[h > 0].mean() if (h > 0).any() else self.E[(cid, sku)][T]
                extra += pr["uplift_plan"] * base * sobre / dias_T
        return extra

    def meta_lancamento(self, sku: int, canal: str, T: int) -> float:
        p = PROD[sku]
        total = self.E_sku_canal[(sku, canal)][T]
        lv = max(fator_ciclo_vida(p, T), 0.3)
        return total / lv * 0.85   # comercial assume rampa bem mais rápida que a real

    def gerar_ciclo(self, C: int):
        lags = LAGS_ULTIMO_CICLO if C == ULTIMO_CICLO else LAGS_POR_CICLO
        vies_canal = {"Varejo Alimentar": 0.06, "Atacarejo": 0.08, "Distribuidor": 0.10,
                      "Food Service": 0.03, "E-commerce": 0.12}
        for canal in CANAIS:
            for sku in sorted(self.canal_skus[canal]):
                p = PROD[sku]
                lm = mes_idx(p["lanc"]) if p["lanc"] else -99
                dm = mes_idx(p["desc"]) if p["desc"] else 999
                if C < lm - 3 or C > dm:
                    continue
                otimismo = rng.normal(vies_canal[canal], 0.07)
                hist_meses = int((self.fat_sc[(sku, canal)][:C] > 0).sum())
                for lag in range(lags + 1):
                    T = C + lag
                    if T < lm or (p["sazonal"] and mes_data(T).month not in MESES_SAZONAL):
                        continue
                    est = self.estatistico(sku, canal, C, T)
                    com = est * (1 + otimismo + rng.normal(0, 0.03 * lag)) + self.promo_conhecida(sku, canal, C, T)
                    if p["lanc"] and hist_meses < 4:
                        com = max(com, self.meta_lancamento(sku, canal, T))
                    if p["sazonal"] and T - 12 >= 0 and T - 12 < C:
                        # comercial planeja a temporada pelo pedido do ano anterior (inclui venda perdida)
                        com = max(com, self.ped_sc[(sku, canal)][T - 12] * (1 + otimismo + 0.10))
                    descontinuacao_conhecida = C >= dm - 1
                    if descontinuacao_conhecida and T > dm:
                        com = 0.0
                    elif descontinuacao_conhecida and T == dm:
                        com = est * 0.5
                    if est <= 0:
                        con = 0.85 * com
                    else:
                        con = est + 0.55 * (com - est)
                    if descontinuacao_conhecida and T > dm:
                        con = 0.0
                    for versao, q in (("Estatístico", est), ("Comercial", com), ("Consenso", con)):
                        q = int(round(max(q, 0) / p["ucx"]) * p["ucx"])
                        self.fc[(C, T, sku, canal, versao)] = q
                        self.forecast_rows.append(dict(Ciclo_SOP=mes_data(C), Data_Mes=mes_data(T), Lag=lag,
                                                       ID_Produto=sku, Canal=canal, Versao=versao, Qtd_Prevista=q))

    def gerar_budget(self, C: int):
        """Orçamento anual (feito em novembro para o ano seguinte), por SKU x canal x mês."""
        ano = mes_data(C).year + 1
        meta = {2025: 0.12, 2026: 0.10}[ano]
        for canal in CANAIS:
            for sku in sorted(self.canal_skus[canal]):
                p = PROD[sku]
                lm = mes_idx(p["lanc"]) if p["lanc"] else -99
                if p["desc"] and mes_idx(p["desc"]) < C:
                    continue
                if lm > mes_idx(date(ano, 12, 1)):
                    continue
                for mes in range(1, 13):
                    T = mes_idx(date(ano, mes, 1))
                    if T < lm or (p["sazonal"] and mes not in MESES_SAZONAL):
                        continue
                    q = self.estatistico(sku, canal, C, T, usar_tendencia=False) * (1 + meta)
                    if p["lanc"] and lm >= C - 3:
                        q = max(q, self.meta_lancamento(sku, canal, T) * 1.1)
                    q = int(round(q / p["ucx"]) * p["ucx"])
                    if q <= 0:
                        continue
                    preco = preco_lista_na_data(p, date(ano, mes, 15)) * (1 - DESC_CANAL[canal] - 0.02)
                    self.budget_rows.append(dict(Ano=ano, Data_Mes=mes_data(T), ID_Produto=sku, Canal=canal,
                                                 Qtd_Budget=q, Valor_Budget=round(q * preco, 2)))

    def forecast_total(self, C: int, T: int, sku: int) -> float | None:
        if C < PRIMEIRO_CICLO:
            return None
        return float(sum(self.fc.get((C, T, sku, canal, "Consenso"), 0) for canal in CANAIS))

    def planejar_producao(self, m: int):
        chegadas = defaultdict(float)  # (data, cd, sku) -> unidades
        for sku in SKUS:
            p = PROD[sku]
            lm = mes_idx(p["lanc"]) if p["lanc"] else -99
            dm = mes_idx(p["desc"]) if p["desc"] else 999
            if m < lm - 1 or m >= dm:
                continue
            esperado = [self.E_sku[sku][m], self.E_sku[sku][m + 1]]
            fc_m = self.forecast_total(m - 1, m, sku)
            fc_prox = self.forecast_total(m - 1, m + 1, sku)
            fc_m = esperado[0] * 1.05 if fc_m is None else fc_m
            fc_prox = esperado[1] * 1.05 if fc_prox is None else fc_prox
            cobertura = {"Ambiente": 0.6, "Congelado": 0.5, "Refrigerado": 0.25}[p["temp"]]
            ei = sum(self.estoque[(cd["ID_CD"], sku)] for cd in CDS)
            q = max(0.0, fc_m + cobertura * fc_prox - ei)
            if sku == 103 and m in (18, 19):
                q *= 0.45   # falta de proteína no fornecedor (jul-ago/2025)
            q *= rng.normal(1, 0.04)
            lote = p["ucx"] * 50
            q = math.ceil(q / lote) * lote if q > 0 else 0
            if q == 0:
                continue
            # rateio entre CDs pelo histórico recente (ou pela demanda esperada)
            hist = {cd["ID_CD"]: self.fat_cd[(sku, cd["ID_CD"])][max(0, m - 3):m].sum() for cd in CDS}
            if sum(hist.values()) == 0:
                hist = {cd["ID_CD"]: self.E_sku_cd[(sku, cd["ID_CD"])][m:m + 2].sum() for cd in CDS}
            tot = sum(hist.values()) or 1.0
            for cd, h in hist.items():
                q_cd = q * h / tot
                for dia in (1, 8, 15, 22):
                    lote_cx = math.floor(q_cd / 4 / p["ucx"])
                    if lote_cx > 0:
                        chegadas[(proximo_dia_util(mes_data(m).replace(day=dia)), cd, sku)] += lote_cx * p["ucx"]
        return chegadas

    def atender_pedidos(self, m: int, chegadas: dict):
        movimento = defaultdict(lambda: defaultdict(float))
        for (d, cd, sku), q in chegadas.items():
            movimento[(cd, sku)]["entrada"] += q
        por_dia = defaultdict(list)
        for ln in self.linhas_por_mes[m]:
            por_dia[ln["Data"]].append(ln)
        chegadas_dia = defaultdict(list)
        for (d, cd, sku), q in chegadas.items():
            chegadas_dia[d].append((cd, sku, q))
        dias_ruptura = defaultdict(set)
        d = mes_data(m)
        while d <= fim_mes(m):
            for cd, sku, q in chegadas_dia.get(d, []):
                self.estoque[(cd, sku)] += q
            lista = por_dia.get(d, [])
            for i in rng.permutation(len(lista)):
                ln = lista[i]
                sku, cd, ucx = ln["ID_Produto"], ln["ID_CD"], PROD[ln["ID_Produto"]]["ucx"]
                pedido = ln["Qtd_Pedida"]
                disponivel_cliente = pedido - ln["corte_previo"]
                estoque = self.estoque[(cd, sku)]
                atendido = min(disponivel_cliente, math.floor(estoque / ucx) * ucx)
                self.estoque[(cd, sku)] = estoque - atendido
                ln["Qtd_Vendida"] = int(atendido)
                ln["Qtd_Cortada"] = int(pedido - atendido)
                if ln["corte_previo"] > 0:
                    ln["Motivo_Corte"] = ln["motivo_previo"]
                elif atendido < pedido:
                    ln["Motivo_Corte"] = "Falta de estoque"
                    dias_ruptura[(cd, sku)].add(d)
                    movimento[(cd, sku)]["corte_falta"] += pedido - atendido
                else:
                    ln["Motivo_Corte"] = ""
                tipo = "venda" if ln["Tipo_Movimento"] == "Venda" else "bonif"
                movimento[(cd, sku)][tipo] += atendido
                if ln["Tipo_Movimento"] == "Venda":
                    self.ped_sc[(sku, CLI[ln["ID_Cliente"]]["canal"])][m] += pedido
                if ln["Tipo_Movimento"] == "Venda" and atendido > 0:
                    canal = CLI[ln["ID_Cliente"]]["canal"]
                    self.fat_sc[(sku, canal)][m] += atendido
                    self.fat_cs[(ln["ID_Cliente"], sku)][m] += atendido
                    self.fat_cat[PROD[sku]["cat"]][m] += atendido
                    self.fat_cd[(sku, cd)][m] += atendido
            d += timedelta(days=1)
        return movimento, dias_ruptura

    def fechar_estoque(self, m: int, movimento: dict, dias_ruptura: dict, estoque_inicial: dict):
        for sku in SKUS:
            p = PROD[sku]
            lm = mes_idx(p["lanc"]) if p["lanc"] else -99
            for cd in (c["ID_CD"] for c in CDS):
                chave = (cd, sku)
                mov = movimento.get(chave, {})
                ei = estoque_inicial.get(chave, 0.0)
                if m < lm - 1 and ei == 0 and not mov:
                    continue
                ef = self.estoque[chave]
                perda_venc, perda_obs = 0.0, 0.0
                if p["desc"] and m > mes_idx(p["desc"]):
                    perda_obs = ef if m >= mes_idx(p["desc"]) + 2 else round(ef * 0.6)
                elif p["shelf"] <= 90 and ef > 0:
                    fc_prox = self.forecast_total(m, m + 1, sku) if m >= PRIMEIRO_CICLO else None
                    if fc_prox is None:
                        fc_prox = self.E_sku[sku][m + 1]
                    hist = {c2["ID_CD"]: self.fat_cd[(sku, c2["ID_CD"])][max(0, m - 2):m + 1].sum() for c2 in CDS}
                    share = hist[cd] / (sum(hist.values()) or 1)
                    permitido = fc_prox * share * min(1.2, p["shelf"] / 30 * 0.6)
                    perda_venc = round(0.4 * max(0.0, ef - permitido))
                    # vencimento "de rotina" no CD (lotes que giraram devagar)
                    perda_venc += round(mov.get("venda", 0) * rng.uniform(0.003, 0.015))
                    perda_venc = min(perda_venc, ef)
                ef = ef - perda_venc - perda_obs
                self.estoque[chave] = ef
                if ei == 0 and ef == 0 and not mov and perda_obs == 0:
                    continue
                self.estoque_rows.append(dict(
                    Data_Mes=mes_data(m), ID_Produto=sku, ID_CD=cd,
                    Estoque_Inicial=int(ei), Entradas_Producao=int(mov.get("entrada", 0)),
                    Saidas_Venda=int(mov.get("venda", 0)), Saidas_Bonificacao=int(mov.get("bonif", 0)),
                    Perdas_Vencimento=int(perda_venc), Perdas_Obsolescencia=int(perda_obs),
                    Estoque_Final=int(ef), Qtd_Cortada_Falta_Estoque=int(mov.get("corte_falta", 0)),
                    Dias_Com_Ruptura=len(dias_ruptura.get(chave, set()))))

    def rodar(self):
        for m in range(N_MESES_REAL + 1):
            if m >= PRIMEIRO_CICLO:
                self.gerar_ciclo(m)
            if m in (10, 22):
                self.gerar_budget(m)
            if m == N_MESES_REAL:
                break
            estoque_inicial = dict(self.estoque)
            chegadas = self.planejar_producao(m)
            movimento, rupturas = self.atender_pedidos(m, chegadas)
            self.fechar_estoque(m, movimento, rupturas, estoque_inicial)


# =============================================================================
# DEVOLUÇÕES, NOTAS FISCAIS E MONTAGEM FINAL
# =============================================================================

MOTIVOS_DEV = {
    "Refrigerado": [("Produto vencido/próximo do vencimento", 0.5), ("Avaria no transporte", 0.2),
                    ("Quebra da cadeia de frio", 0.2), ("Erro de pedido", 0.1)],
    "Congelado": [("Quebra da cadeia de frio", 0.4), ("Avaria no transporte", 0.35), ("Erro de pedido", 0.15),
                  ("Recusa no recebimento", 0.1)],
    "Ambiente": [("Avaria no transporte", 0.55), ("Erro de pedido", 0.25), ("Recusa no recebimento", 0.2)],
}


def gerar_devolucoes(linhas: list[dict]) -> list[dict]:
    devs = []
    seq = 1
    for ln in linhas:
        if ln["Tipo_Movimento"] != "Venda" or ln["Qtd_Vendida"] <= 0:
            continue
        p = PROD[ln["ID_Produto"]]
        taxa = 0.09 if p["temp"] == "Refrigerado" else 0.04
        if rng.random() > taxa:
            continue
        d = proximo_dia_util(ln["Data"] + timedelta(days=int(rng.integers(3, 26))))
        if d > FIM_VENDAS:
            continue
        q = max(1, int(ln["Qtd_Vendida"] * rng.uniform(0.03, 0.35)))
        motivos, probs = zip(*MOTIVOS_DEV[p["temp"]])
        liq = ln["Preco_Unitario_Liquido"]
        devs.append(dict(
            ID_Pedido=ln["ID_Pedido"], Nr_Nota_Fiscal=f"D{seq:06d}", Data_Pedido=ln["Data_Pedido"], Data=d,
            ID_Cliente=ln["ID_Cliente"], ID_Produto=ln["ID_Produto"], ID_CD=ln["ID_CD"], Tipo_Movimento="Devolução",
            Qtd_Pedida=0, Qtd_Vendida=-q, Qtd_Cortada=0, Motivo_Corte="",
            Preco_Unitario_Lista=ln["Preco_Unitario_Lista"], Desconto_Comercial_Pct=ln["Desconto_Comercial_Pct"],
            Desconto_Promocional_Pct=ln["Desconto_Promocional_Pct"], Preco_Unitario_Liquido=liq,
            Valor_Bruto=round(-q * ln["Preco_Unitario_Lista"], 2), Valor_Liquido=round(-q * liq, 2),
            ID_Promocao=ln["ID_Promocao"], Motivo_Devolucao=str(rng.choice(motivos, p=probs))))
        seq += 1
    return devs


def finalizar_vendas(linhas: list[dict]) -> pd.DataFrame:
    for ln in linhas:
        if ln["Tipo_Movimento"] == "Bonificação":
            ln["Preco_Unitario_Liquido"] = 0.0
        else:
            desc = (ln["Desconto_Comercial_Pct"] + ln["Desconto_Promocional_Pct"]) / 100
            ln["Preco_Unitario_Liquido"] = round(ln["Preco_Unitario_Lista"] * (1 - desc), 2)
        ln["Valor_Bruto"] = round(ln["Qtd_Vendida"] * ln["Preco_Unitario_Lista"], 2)
        ln["Valor_Liquido"] = round(ln["Qtd_Vendida"] * ln["Preco_Unitario_Liquido"], 2)
        ln["Motivo_Devolucao"] = ""
    # numeração de pedidos em ordem cronológica (como no ERP)
    chave_pedido = {}
    for ln in linhas:
        chave_pedido.setdefault(ln["ID_Pedido"], (ln["Data_Pedido"], ln["ID_Cliente"]))
    novo_id = {antigo: f"PV{i:07d}" for i, antigo in enumerate(sorted(chave_pedido, key=chave_pedido.get), start=1)}
    for ln in linhas:
        ln["ID_Pedido"] = novo_id[ln["ID_Pedido"]]
    # numeração de NF por CD, uma NF por pedido que teve algo faturado
    pedidos = defaultdict(list)
    for ln in linhas:
        pedidos[ln["ID_Pedido"]].append(ln)
    contador = {"CD01": 100000, "CD02": 500000}
    for pid in sorted(pedidos, key=lambda x: (pedidos[x][0]["Data"], x)):
        grupo = pedidos[pid]
        if any(g["Qtd_Vendida"] > 0 for g in grupo):
            cd = grupo[0]["ID_CD"]
            contador[cd] += 1
            nf = f"{cd[-2:]}-{contador[cd]:06d}"
        else:
            nf = ""
        for g in grupo:
            g["Nr_Nota_Fiscal"] = nf if g["Qtd_Vendida"] > 0 else ""
    todas = linhas + gerar_devolucoes(linhas)
    colunas = ["ID_Pedido", "Nr_Nota_Fiscal", "Data_Pedido", "Data", "ID_Cliente", "ID_Produto", "ID_CD",
               "Tipo_Movimento", "Qtd_Pedida", "Qtd_Vendida", "Qtd_Cortada", "Motivo_Corte",
               "Preco_Unitario_Lista", "Desconto_Comercial_Pct", "Desconto_Promocional_Pct",
               "Preco_Unitario_Liquido", "Valor_Bruto", "Valor_Liquido", "ID_Promocao", "Motivo_Devolucao"]
    df = pd.DataFrame(todas)[colunas]
    ordem_tipo = {"Venda": 0, "Bonificação": 1, "Devolução": 2}
    df["_o"] = df["Tipo_Movimento"].map(ordem_tipo)
    df = df.sort_values(["Data", "ID_Pedido", "_o", "ID_Produto"]).drop(columns="_o").reset_index(drop=True)
    return df


def ean13(sku: int) -> str:
    base = f"2900000{sku:05d}"   # prefixo 2xx = uso interno/restrito (não colide com EAN real)
    soma = sum(int(dig) * (1 if i % 2 == 0 else 3) for i, dig in enumerate(base))
    return base + str((10 - soma % 10) % 10)


def montar_d_produto(vendas: pd.DataFrame) -> pd.DataFrame:
    v = vendas[vendas["Tipo_Movimento"] == "Venda"].copy()
    v["Mes"] = v["Data"].map(mes_idx)
    janela = v[v["Mes"] >= N_MESES_REAL - 12]
    receita = janela.groupby("ID_Produto")["Valor_Liquido"].sum().reindex(SKUS, fill_value=0).sort_values(ascending=False)
    acum = receita.cumsum() / receita.sum()
    abc = {}
    anterior = 0.0
    for sku, pct in acum.items():
        abc[sku] = "A" if anterior < 0.80 else ("B" if anterior < 0.95 else "C")
        anterior = pct
    mensal = janela.groupby(["ID_Produto", "Mes"])["Qtd_Vendida"].sum()
    linhas = []
    for p in PRODUTOS:
        lm = mes_idx(p["lanc"]) if p["lanc"] else -99
        meses = [m for m in range(max(N_MESES_REAL - 12, lm), N_MESES_REAL)
                 if not (p["sazonal"] and mes_data(m).month not in MESES_SAZONAL)]
        serie = np.array([mensal.get((p["id"], m), 0) for m in meses], dtype=float)
        if len(serie) >= 3 and serie.mean() > 0:
            cv = serie.std() / serie.mean()
            xyz = "X" if cv <= 0.25 else ("Y" if cv <= 0.50 else "Z")
        else:
            xyz = "Z"
        if p["desc"] and p["desc"] <= DATA_REFERENCIA:
            status = "Descontinuado"
        elif p["lanc"] and p["lanc"] >= DATA_REFERENCIA - timedelta(days=183):
            status = "Lançamento"
        elif p["sazonal"]:
            status = "Ativo - Sazonal"
        else:
            status = "Ativo"
        linhas.append(dict(
            ID_Produto=p["id"], EAN=ean13(p["id"]), Nome_Produto=p["nome"], Marca=p["marca"], Categoria=p["cat"],
            Subcategoria=p["sub"], Embalagem=p["emb"], Conteudo=p["cont"], Temperatura=p["temp"],
            Shelf_Life_Dias=p["shelf"], Unid_por_Caixa=p["ucx"], Preco_Lista=f"{p['preco']:.2f}",
            Custo_Unitario=f"{p['custo']:.2f}", Data_Lancamento=p["cad"], Data_Descontinuacao=p["desc"],
            ID_Produto_Substituto=p["subst"], Status_Ciclo_Vida=status, Sazonal=int(p["sazonal"]),
            Classificacao_ABC=abc[p["id"]], Classificacao_XYZ=xyz))
    df = pd.DataFrame(linhas)
    df["ID_Produto_Substituto"] = df["ID_Produto_Substituto"].astype("Int64")
    return df


def montar_d_cliente() -> pd.DataFrame:
    linhas = []
    for c in CLIENTES:
        linhas.append(dict(
            ID_Cliente=c["id"], Nome_Cliente=c["nome"], Grupo_Economico=c["grupo"], Canal=c["canal"],
            Subcanal=c["sub"], Tipo_Atendimento=c["tipo"], Regiao=c["regiao"], UF=c["uf"], Cidade=c["cidade"],
            ID_CD=c["cd"], Porte=c["porte"],
            Frequencia_Pedido={"S": "Semanal", "2S": "2x por semana", "Q": "Quinzenal"}[c["freq"]],
            Lead_Time_Dias=LEAD_TIME_UF[c["uf"]], Executivo_Contas=c["exec"],
            Data_Inicio_Relacionamento=c["ini"], Status="Inativo" if c["inat"] else "Ativo",
            Data_Inativacao=c["inat"]))
    return pd.DataFrame(linhas)


# =============================================================================
# VERSÃO "SUJA" OPCIONAL (para treinar limpeza no ETL)
# =============================================================================

def sujar(tabelas: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    r = np.random.default_rng(SEED + 1)
    v = tabelas["f_Vendas"].copy()
    v["Data"] = v["Data"].map(lambda d: d.strftime(FMT))
    v["ID_Produto"] = v["ID_Produto"].astype(object)
    # 1) linhas duplicadas (reprocessamento de interface)
    dup = v.sample(frac=0.003, random_state=1)
    # 2) datas em formato ISO no meio do arquivo (extração de outro sistema)
    idx = v.sample(frac=0.01, random_state=2).index
    v.loc[idx, "Data"] = pd.to_datetime(v.loc[idx, "Data"], format=FMT).dt.strftime("%Y-%m-%d")
    # 3) SKU com zero à esquerda (vem como texto do Excel)
    idx = v.sample(frac=0.01, random_state=3).index
    v.loc[idx, "ID_Produto"] = [f"0{s}" for s in v.loc[idx, "ID_Produto"]]
    # 4) código antigo que não existe no cadastro
    idx = v.sample(n=40, random_state=4).index
    v.loc[idx, "ID_Produto"] = 99
    # 5) preço faltando
    idx = v.sample(frac=0.002, random_state=5).index
    v.loc[idx, ["Preco_Unitario_Lista", "Valor_Bruto"]] = np.nan
    v = pd.concat([v, dup]).sample(frac=1, random_state=6).reset_index(drop=True)
    c = tabelas["d_Cliente"].copy()
    c.loc[r.choice(len(c), 5, replace=False), "Nome_Cliente"] += "  "
    c.loc[r.choice(len(c), 4, replace=False), "Canal"] = c["Canal"].str.upper()
    c.loc[r.choice(len(c), 3, replace=False), "Regiao"] = None
    return {"f_Vendas": v, "d_Cliente": c}


# =============================================================================
# EXECUÇÃO
# =============================================================================

def formatar_datas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        amostra = df[col].dropna()
        if len(amostra) and isinstance(amostra.iloc[0], date):
            df[col] = df[col].map(lambda x: x.strftime(FMT) if isinstance(x, date) else x)
    return df


def main():
    parser = argparse.ArgumentParser(description="Gera a base simulada do projeto.")
    parser.add_argument("--saida", type=Path, default=DADOS_DIR)
    parser.add_argument("--com-problemas", action="store_true",
                        help="gera também uma cópia com problemas típicos de qualidade de dados")
    args = parser.parse_args()
    saida: Path = args.saida
    saida.mkdir(parents=True, exist_ok=True)

    print("1/6 Montando sortimento e demanda esperada...")
    sort = montar_sortimento()
    E = montar_demanda_esperada(sort)
    print("2/6 Gerando promoções...")
    promos, promos_chave = gerar_promocoes(sort)
    print("3/6 Gerando pedidos...")
    linhas = gerar_pedidos(sort, E, promos_chave)
    print("4/6 Simulando ciclos de S&OP, produção, estoque e atendimento...")
    sim = Simulador(sort, E, promos, promos_chave, linhas)
    sim.rodar()
    print("5/6 Montando tabelas finais...")
    vendas = finalizar_vendas(linhas)

    fh = pd.DataFrame(sim.forecast_rows)
    oficial = fh[(fh["Versao"] == "Consenso") & (fh["Lag"] == 1) & (fh["Data_Mes"] <= mes_data(N_MESES_REAL - 1))]
    piv = (fh[(fh["Lag"] == 1) & (fh["Data_Mes"] <= mes_data(N_MESES_REAL - 1))]
           .pivot_table(index=["Data_Mes", "ID_Produto", "Ciclo_SOP"], columns="Versao",
                        values="Qtd_Prevista", aggfunc="sum", fill_value=0).reset_index())
    f_forecast = pd.DataFrame({
        "Data_Mes": piv["Data_Mes"], "ID_Produto": piv["ID_Produto"], "Qtd_Prevista": piv["Consenso"],
        "Qtd_Prevista_Estatistica": piv["Estatístico"], "Qtd_Prevista_Comercial": piv["Comercial"],
        "Ciclo_SOP": piv["Ciclo_SOP"]})
    f_forecast = f_forecast[(f_forecast[["Qtd_Prevista", "Qtd_Prevista_Estatistica", "Qtd_Prevista_Comercial"]] > 0).any(axis=1)]
    f_forecast = f_forecast.sort_values(["Data_Mes", "ID_Produto"]).reset_index(drop=True)
    assert f_forecast["Qtd_Prevista"].sum() == oficial["Qtd_Prevista"].sum()

    tabelas = {
        "d_Calendario": gerar_calendario(),
        "d_Produto": montar_d_produto(vendas),
        "d_Cliente": montar_d_cliente(),
        "d_CentroDistribuicao": pd.DataFrame(CDS),
        "f_Vendas": vendas,
        "f_Forecast": f_forecast,
        "f_Forecast_Historico": fh.sort_values(["Ciclo_SOP", "Data_Mes", "ID_Produto", "Canal", "Versao"]).reset_index(drop=True),
        "f_Budget": pd.DataFrame(sim.budget_rows).sort_values(["Data_Mes", "ID_Produto", "Canal"]).reset_index(drop=True),
        "f_Promocoes": pd.DataFrame(promos).sort_values(["Data_Inicio", "ID_Promocao", "ID_Cliente", "ID_Produto"]).reset_index(drop=True),
        "f_Estoque": pd.DataFrame(sim.estoque_rows).sort_values(["Data_Mes", "ID_Produto", "ID_CD"]).reset_index(drop=True),
    }

    print("6/6 Gravando CSVs...")
    for nome, df in tabelas.items():
        formatar_datas(df).to_csv(saida / f"{nome}.csv", index=False, encoding="utf-8")
        print(f"   {nome:<22} {len(df):>8,} linhas")

    if args.com_problemas:
        pasta = saida / "_brutos_com_problemas"
        pasta.mkdir(exist_ok=True)
        for nome, df in sujar(tabelas).items():
            formatar_datas(df).to_csv(pasta / f"{nome}.csv", index=False, encoding="utf-8")
        print(f"   versão com problemas gravada em {pasta}")
    print("Concluído.")


if __name__ == "__main__":
    main()
