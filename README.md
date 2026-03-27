# 📊 Demand Planning Accuracy Dashboard (S&OP)

## 📌 Contexto do Negócio
No setor de bens de consumo, errar a previsão de demanda gera dois problemas críticos: a **ruptura** (perda de vendas e insatisfação do cliente) e o **excesso de estoque** (capital de giro preso e risco de validade/shelf life). 

Este projeto simula os dados de uma empresa de alimentos, comparando as Vendas Realizadas (Actuals) com a Previsão de Demanda (Forecast). O objetivo é fornecer visibilidade sobre a acurácia do planejamento e assim auxiliar na tomada de decisão do time de S&OP.

## 🛠️ Ferramentas que serão Utilizadas
* **Power BI:** Criação do Dashboard, modelagem de dados e visualização.
* **DAX:** Criação de medidas complexas (Inteligência de Tempo, MAPE, BIAS).
* **Power Query:** Processo de ETL (Limpeza e transformação dos dados brutos).
* **Excel / CSV:** Base de dados simulada estruturada a partir de lógicas de ERP (ex: SAP S/4 HANA).

## 🧮 KPIs e Métricas Analisadas
Para avaliar o planejamento de demanda, serão criados os seguintes indicadores de desempenho:
* **Forecast Accuracy (Acurácia):** O percentual de acerto do plano original.
* **WMAPE (Weighted Mean Absolute Percentage Error):** Mede o tamanho absoluto do erro, ponderado pelo volume ou valor financeiro do produto. Produtos Curva A têm maior peso no indicador.
* **BIAS (Viés da Previsão):** Indica a direção do erro. 
  * *BIAS Positivo:* Previsão maior que a venda real (Risco de excesso de estoque).
  * *BIAS Negativo:* Previsão menor que a venda real (Risco de ruptura).

## 🏗️ Arquitetura e Modelagem de Dados
O modelo será construído seguindo as práticas do **Star Schema** (Esquema Estrela) para garantir performance no Power BI:
* **Tabelas Fato:** `f_Vendas_Realizadas`, `f_Forecast_Baseline`
* **Tabelas Dimensão:** `d_Calendario`, `d_Produto` (com classificação ABC), `d_Clientes`
