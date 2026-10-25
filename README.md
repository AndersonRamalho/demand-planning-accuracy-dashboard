# 📊 Demand Planning Accuracy Dashboard (S&OP)

## 📌 Contexto do Negócio
No setor de bens de consumo, errar a previsão de demanda gera dois problemas críticos: a **ruptura** (perda de vendas e insatisfação do cliente) e o **excesso de estoque** (capital de giro preso e risco de validade/shelf life). 

Este projeto simula os dados de uma empresa de alimentos, comparando as Vendas Realizadas (Actuals) com a Previsão de Demanda (Forecast). O objetivo é fornecer visibilidade sobre a acurácia do planejamento e assim auxiliar na tomada de decisão do time de S&OP.

## 🛠️ Ferramentas que serão Utilizadas
* **Python (Pandas):** Processo de ETL — limpeza, transformação e cálculo dos KPIs de planejamento.
* **SQL (SQLite):** Consultas analíticas, JOINs e agregações sobre os dados de demanda e vendas.
* **Plotly:** Criação de gráficos interativos (barras, linhas, gauges, heatmaps)
* **HTML / CSS / JavaScript:** Dashboard interativo estático, sem necessidade de servidor.
* **Jinja2:** Motor de templates para gerar o HTML final a partir dos dados processados.
* **Requests:** Consumo de APIs externas (IBGE, BrasilAPI) para enriquecimento de dados.
* **CSV:** Base de dados simulada estruturada a partir de lógicas de ERP (ex: SAP S/4 HANA).

## 🧮 KPIs e Métricas Analisadas
Para avaliar o planejamento de demanda, serão criados os seguintes indicadores de desempenho:
* **Forecast Accuracy (Acurácia):** O percentual de acerto do plano original.
* **WMAPE (Weighted Mean Absolute Percentage Error):** Mede o tamanho absoluto do erro, ponderado pelo volume ou valor financeiro do produto. Produtos Curva A têm maior peso no indicador.
* **BIAS (Viés da Previsão):** Indica a direção do erro. 
  * *BIAS Positivo:* Previsão maior que a venda real (Risco de excesso de estoque).
  * *BIAS Negativo:* Previsão menor que a venda real (Risco de ruptura).

## 🗄️ SQL — Consultas Analíticas com SQLite
Os CSVs são carregados em um banco **SQLite em memória**, permitindo praticar SQL real sobre os dados do projeto:
* **JOINs** entre tabelas fato e dimensão (Star Schema).
* **Agregações** (`SUM`, `GROUP BY`) para totalizar vendas por produto/mês.
* **Cálculo de KPIs via SQL** (WMAPE, Accuracy, BIAS) usando `CASE`, `ABS`, subqueries.
* **Views** para encapsular consultas complexas e reutilizá-las nos gráficos.

## 🌐 APIs — Enriquecimento de Dados Externos
O projeto inclui um módulo de consumo de APIs públicas brasileiras para aprender os conceitos de integração:
* **API IBGE (Localidades):** Busca lista de estados e municípios para enriquecer a dimensão de clientes com dados geográficos reais.
* **BrasilAPI / ReceitaWS (CNPJ):** Consulta dados cadastrais de empresas a partir do CNPJ (razão social, endereço, situação cadastral) — simula o enriquecimento de cadastro de clientes/fornecedores.

As APIs são públicas e gratuitas, servindo como laboratório para entender requisições HTTP, JSON parsing e tratamento de erros.

## 🏗️ Arquitetura e Modelagem de Dados
O modelo será construído seguindo as práticas do **Star Schema** (Esquema Estrela):
* **Tabelas Fato:** `f_Vendas`, `f_Forecast`
* **Tabelas Dimensão:** `d_Calendario`, `d_Produto` (com classificação ABC), `d_Clientes`

```
demand-planning-accuracy-dashboard/
├── Dados/                          # CSVs com dados simulados (Star Schema)
│   ├── d_Cliente.csv               # Dimensão: Clientes e canais
│   ├── d_Produto.csv               # Dimensão: Produtos e classificação ABC
│   ├── f_Forecast.csv              # Fato: Previsão de demanda por mês
│   └── f_Vendas.csv                # Fato: Vendas realizadas
├── src/                            # Código-fonte Python
│   ├── etl.py                      # Leitura, limpeza e carga no SQLite
│   ├── kpis.py                     # Cálculo de Accuracy, WMAPE, BIAS (Pandas + SQL)
│   ├── apis.py                     # Consumo de APIs externas (IBGE, CNPJ)
│   └── generate_dashboard.py       # Gera os gráficos e monta o HTML final
├── templates/                      # Templates Jinja2 do dashboard
│   └── dashboard.html              # Template base do HTML
├── output/                         # Artefato final gerado
│   └── dashboard.html              # Dashboard pronto para abrir no navegador
├── requirements.txt                # Dependências do projeto
└── README.md
​```

## 🚀 Como Executar
1. Clone o repositório:
   ​```bash
   git clone https://github.com/SEU_USUARIO/demand-planning-accuracy-dashboard.git
   cd demand-planning-accuracy-dashboard
   ​```
2. Crie um ambiente virtual e instale as dependências:
   ​```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   ​```
3. Gere o dashboard:
   ​```bash
   python src/generate_dashboard.py
   ​```4. Abra o arquivo `output/dashboard.html` no navegador.