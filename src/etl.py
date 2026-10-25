import sqlite3
import pandas as pd
from pathlib import Path


# Localização dinâmica da pasta de dados
BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "Dados"


def carregar_dados_sqlite():
    """
    Lê os 4 CSVs de dados brutos, trata os formatos de data e tipos,
    e carrega as tabelas em um SQLite em memória RAM (:memory).
    Retorna a conexão aberta `conn`.
    """
    conn = sqlite3.connect(":memory:")

    #  1. Carregar e padronizar f_Vendas
    df_vendas = pd.read_csv(DADOS_DIR / "f_Vendas.csv")
    df_vendas["Data"] = pd.to_datetime(
        df_vendas["Data"], format="%d/%m/%Y"
    ).dt.strftime("%Y-%m-%d")

    # 2. Carregar e padronizar f_Forecast
    df_forecast = pd.read_csv(DADOS_DIR / "f_Forecast.csv")
    df_forecast["Data_Mes"] = pd.to_datetime(
        df_forecast["Data_Mes"], format="%d/%m/%Y"
    ).dt.strftime("%Y-%m-%d")

    # 3. Carregar d_Produto
    df_produto = pd.read_csv(DADOS_DIR / "d_Produto.csv")
    df_produto["Custo_Unitario"] = df_produto["Custo_Unitario"].astype(float)

    # 4. Carregar d_Cliente
    df_cliente = pd.read_csv(DADOS_DIR / "d_Cliente.csv")

    # 5. Inserir no SQLite
    df_vendas.to_sql("f_vendas", conn, index=False, if_exists="replace")
    df_forecast.to_sql("f_forecast", conn, index=False, if_exists="replace")
    df_produto.to_sql("d_produto", conn, index=False, if_exists="replace")
    df_cliente.to_sql("d_cliente", conn, index=False, if_exists="replace")

    return conn


if __name__ == "__main__":
    # Teste de execução individual do script
    print(" Executando ETL e criando banco SQLite...")
    conn = carregar_dados_sqlite()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tabelas = [row[0] for row in cursor.fetchall()]
    print(f"Sucesso! Tabelas criadas no SQLite: {tabelas}")
