import pandas as pd
from etl import carregar_dados_sqlite


def criar_view_analitica(conn):
    """
    Criar a VIEW SQL 'v_base_comparativa' que unifica as vendas agregadas
    com o forecast e dimensões de produto.
    """
    query_view = """
    CREATE VIEW IF NOT EXISTS v_base_comparativa AS
    WITH vendas_mensais AS (
        SELECT
            strftime('%Y-%m-01', Data) AS Data_mes,
            ID_Produto,
            SUM(Qtd_Vendida) AS Realizado
        FROM f_vendas
        GROUP BY strftime('%Y-%m-01', Data), ID_Produto
    )
    SELECT
        f.Data_Mes,
        strftime('%Y', f.Data_Mes) AS Ano_Mes,
        p.ID_Produto,
        p.Nome_Produto,
        p.Categoria,
        p.Classificacao_ABC,
        p.Custo_Unitario,
        COALESCE(v.Realizado, 0) AS Realizado,
        f.Qtd_Prevista AS Previsto,
        (f.Qtd_Prevista - COALESCE(v.Realizado, 0)) AS Erro_Com_Sinal,
        ABS(f.Qtd_Prevista - COALESCE(v.Realizado, 0)) AS Erro_Absoluto,
        (COALESCE(v.Realizado, 0) * p.Custo_Unitario) AS Valor_Realizado,
        (f.Qtd_Prevista * p.Custo_Unitario) AS Valor_Previsto
    FROM f_forecast f
    LEFT JOIN vendas_mensais v
        ON f.Data_Mes = v.Data_Mes AND f.ID_Produto = v.ID_Produto
    INNER JOIN d_produto p
        ON f.ID_Produto = p.ID_Produto;
    """
    cursor = conn.cursos()
    cursor.execute(query_view)
    conn.commit()


def calcular_kpis(conn):
    """
    Executa as queries SQL analíticas sobre a VIEW e retorna:
    1. kpis_gerais (dict): Indicadores totais para os cards do topo.
    2. df_mensal (DataFrame): Evolução mês a mês para gráficos de linha/barra.
    3. df_produto (DataFrame): Desempenho por SKU, Curva ABC e Categoria.
    """
    # 1. Garante que a VIEW existe no banco
    criar_view_analitica(conn)
    # 2. Query 1: KPIs Gerais Consolidados da Empresa
    sql_geral = """
    SELECT 
        SUM(Realizado) AS Total_Realizado,
        SUM(Previsto) AS Total_Previsto,
        SUM(Erro_Absoluto) AS Total_Erro_Absoluto,
        ROUND((CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado)) * 100, 2) AS WMAPE_Pct,
        ROUND((1.0 - (CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado))) * 100, 2) AS Accuracy_Pct,
        ROUND((CAST(SUM(Erro_Com_Sinal) AS REAL) / SUM(Realizado)) * 100, 2) AS BIAS_Pct
    FROM v_base_comparativa;
    """
    df_geral = pd.read_sql_query(sql_geral, conn)
    # 3. Query 2: Evolução Mensal (para gráficos temporais)
    sql_mensal = """
    SELECT 
        Ano_Mes,
        SUM(Realizado) AS Realizado,
        SUM(Previsto) AS Previsto,
        ROUND((1.0 - (CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado))) * 100, 2) AS Accuracy_Pct,
        ROUND((CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado)) * 100, 2) AS WMAPE_Pct,
        ROUND((CAST(SUM(Erro_Com_Sinal) AS REAL) / SUM(Realizado)) * 100, 2) AS BIAS_Pct
    FROM v_base_comparativa
    GROUP BY Ano_Mes
    ORDER BY Ano_Mes;
    """
    df_mensal = pd.read_sql_query(sql_mensal, conn)
    # 4. Query 3: KPIs por Produto (Detalhamento SKU e Curva ABC)
    sql_produto = """
    SELECT 
        ID_Produto,
        Nome_Produto,
        Categoria,
        Classificacao_ABC,
        SUM(Realizado) AS Realizado,
        SUM(Previsto) AS Previsto,
        ROUND((CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado)) * 100, 2) AS WMAPE_Pct,
        ROUND((1.0 - (CAST(SUM(Erro_Absoluto) AS REAL) / SUM(Realizado))) * 100, 2) AS Accuracy_Pct,
        ROUND((CAST(SUM(Erro_Com_Sinal) AS REAL) / SUM(Realizado)) * 100, 2) AS BIAS_Pct
    FROM v_base_comparativa
    GROUP BY ID_Produto, Nome_Produto, Categoria, Classificacao_ABC
    ORDER BY WMAPE_Pct DESC;
    """
    df_produto = pd.read_sql_query(sql_produto, conn)
    # Consolida os KPIs em formato de dicionário simples
    kpis_gerais = {
        "accuracy": df_geral["Accuracy_Pct"].iloc[0],
        "wmape": df_geral["WMAPE_Pct"].iloc[0],
        "bias": df_geral["BIAS_Pct"].iloc[0],
        "total_realizado": int(df_geral["Total_Realizado"].iloc[0]),
        "total_previsto": int(df_geral["Total_Previsto"].iloc[0]),
    }
    return kpis_gerais, df_mensal, df_produto
