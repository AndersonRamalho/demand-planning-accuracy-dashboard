# 📚 Dicionário de Dados — Demand Planning Accuracy Dashboard

Base **fictícia** que simula o que um planejador de demanda recebe no dia a dia: extração de pedidos/faturamento do ERP, versões de forecast de cada ciclo de S&OP, orçamento anual, calendário promocional e posição de estoque.

Todos os nomes de clientes, marcas, pessoas, EANs e números são inventados.

- **Período realizado:** 01/01/2024 a 30/09/2026 (33 meses fechados)
- **Ciclos de S&OP:** abr/2024 a out/2026 (o ciclo de out/2026 projeta até mar/2027)
- **Unidade de quantidade:** sempre **unidades (UN)**. A caixa fechada está em `d_Produto.Unid_por_Caixa`, e os pedidos são sempre feitos em múltiplos dela
- **Valores:** R$, separador decimal `.`
- **Datas:** `dd/mm/aaaa` (mesmo padrão dos CSVs originais)
- **Encoding:** UTF-8, separador `,`

Os arquivos são gerados por `src/gerar_dados_simulados.py` com uma semente fixa. Quem rodar o script de novo obtém exatamente os mesmos dados.

---

## 🗺️ Modelo (Star Schema)

```
                     d_Calendario (Data)
                            │
d_Cliente ──┬── f_Vendas ───┼── d_Produto ──┬── f_Forecast            (SKU x mês)
(ID_Cliente)│  (pedido x    │  (ID_Produto) ├── f_Forecast_Historico (ciclo x mês x lag x SKU x canal x versão)
            │   SKU x tipo) │               ├── f_Budget              (mês x SKU x canal)
            ├── f_Promocoes ┘               └── f_Estoque             (mês x SKU x CD)
            │                                         │
            └────────── d_CentroDistribuicao (ID_CD) ─┘
```

Atenção: **o forecast está no nível SKU x Canal x Mês**, e as vendas estão no nível **pedido x cliente x SKU x dia**. Para comparar os dois, é preciso agregar as vendas e trazer o `Canal` pela `d_Cliente`.

---

## 📐 Dimensões

### `d_Calendario.csv` — 1 linha por dia (01/01/2024 a 31/03/2027)
| Coluna | Descrição |
|---|---|
| Data | Data do dia |
| Ano, Trimestre, Mes, Nome_Mes | Atributos de data |
| Ano_Mes | Texto `aaaa-mm` (útil para agrupar) |
| Primeiro_Dia_Mes | Chave para juntar com tabelas mensais (`Data_Mes`) |
| Semana_ISO, Ano_Semana_ISO | Semana ISO (segunda a domingo) |
| Dia_Semana_Num, Dia_Semana | 1 = segunda … 7 = domingo |
| Fim_de_Semana | 1/0 |
| Feriado, Tipo_Feriado | Feriados nacionais e pontos facultativos (Carnaval, Corpus Christi) |
| Dia_Util | 1/0. Regra do projeto: Carnaval **não** é dia útil e Corpus Christi **é** |
| Dias_Uteis_Mes | Total de dias úteis do mês |
| Dia_Util_do_Mes | Posição do dia útil no mês (0 se não for útil) |
| Data_Comercial | Páscoa, Dia das Mães, Dia dos Pais, Black Friday etc. |

### `d_Produto.csv` — 1 linha por SKU (30 SKUs)
| Coluna | Descrição |
|---|---|
| ID_Produto | Código do material (chave). Os 4 SKUs originais (101–104) foram mantidos |
| EAN | Código de barras (13 dígitos, prefixo 2 = uso interno). **Leia como texto:** `dtype={"EAN": str}` |
| Nome_Produto, Marca | Descrição e marca (fictícia) |
| Categoria, Subcategoria | Bebidas, Condimentos, Congelados, Sobremesas, Refrigerados |
| Embalagem, Conteudo | Tipo de embalagem e conteúdo líquido |
| Temperatura | Ambiente, Congelado ou Refrigerado |
| Shelf_Life_Dias | Vida útil total em dias |
| Unid_por_Caixa | Unidades por caixa de embarque (lote mínimo de pedido) |
| Preco_Lista | Preço de tabela **atual** (após o reajuste de mar/2026). O preço histórico de cada venda está na `f_Vendas` |
| Custo_Unitario | Custo atual por unidade |
| Data_Lancamento | Data de cadastro/lançamento |
| Data_Descontinuacao | Preenchida apenas para SKUs descontinuados |
| ID_Produto_Substituto | SKU que substitui o descontinuado (phase-in/phase-out) |
| Status_Ciclo_Vida | Ativo, Lançamento (≤ 6 meses), Ativo - Sazonal, Descontinuado (referência: 26/10/2026) |
| Sazonal | 1 = vendido só de novembro a março |
| Classificacao_ABC | Curva ABC por receita líquida dos últimos 12 meses (out/25–set/26): A até 80% acumulado, B até 95%, C o restante |
| Classificacao_XYZ | Variabilidade da demanda mensal no mesmo período (CV): X ≤ 0,25, Y ≤ 0,50, Z > 0,50 ou histórico insuficiente. *Os limites são uma convenção deste projeto; cada empresa define os seus* |

### `d_Cliente.csv` — 1 linha por cliente/local de entrega (47 clientes)
| Coluna | Descrição |
|---|---|
| ID_Cliente | Código do cliente (chave) |
| Nome_Cliente | Razão/local de entrega (ex.: CD da rede em cada estado) |
| Grupo_Economico | Grupo ao qual o cliente pertence (vários CDs = um grupo) |
| Canal | Varejo Alimentar, Atacarejo, Distribuidor, Food Service, E-commerce |
| Subcanal | Supermercado, Hipermercado, Proximidade, Rede de Fast Food, Cafeterias, Marketplace… |
| Tipo_Atendimento | Direto ou Indireto (distribuidores) |
| Regiao, UF, Cidade | Localização (sem código IBGE, que pode ser buscado na API do IBGE na Fase 4) |
| ID_CD | CD que atende o cliente |
| Porte | Grande, Médio, Pequeno |
| Frequencia_Pedido | Semanal, 2x por semana, Quinzenal |
| Lead_Time_Dias | Prazo de entrega a partir do CD |
| Executivo_Contas | Responsável comercial |
| Data_Inicio_Relacionamento | Início do relacionamento (alguns começam dentro do período) |
| Status, Data_Inativacao | Clientes perdidos ficam como Inativo |

### `d_CentroDistribuicao.csv` — 2 CDs
`ID_CD`, `Nome_CD`, `Cidade`, `UF`, `Regiao`, `Tipo_Operacao`, `Regioes_Atendidas`. O CD01 (SP) atende Sudeste, Sul e Centro-Oeste, e o CD02 (PE) atende Nordeste e Norte. Produtos refrigerados de vida curta não são enviados para N/NE.

---

## 📊 Fatos

### `f_Vendas.csv` — 1 linha por pedido x SKU x tipo de movimento (~95 mil linhas)
Simula a extração de itens de pedido/faturamento do ERP.

| Coluna | Descrição |
|---|---|
| ID_Pedido | Número do pedido de venda (sequencial no tempo) |
| Nr_Nota_Fiscal | NF de saída (`01-…` = CD01, `02-…` = CD02). **Vazio** quando o item não foi faturado (corte total). Devoluções usam `D…` |
| Data_Pedido | Data em que o cliente fez o pedido |
| Data | **Data de faturamento** (D+1 útil do pedido; é a coluna usada pelo `etl.py`). Na virada do mês, um pedido do dia 31 pode faturar no mês seguinte |
| ID_Cliente, ID_Produto, ID_CD | Chaves |
| Tipo_Movimento | `Venda`, `Bonificação` (mercadoria sem cobrança) ou `Devolução` |
| Qtd_Pedida | O que o cliente pediu = **demanda** (0 nas devoluções) |
| Qtd_Vendida | O que foi faturado. **Negativo nas devoluções** |
| Qtd_Cortada | Qtd_Pedida − Qtd_Vendida |
| Motivo_Corte | Falta de estoque, Bloqueio de crédito, Shelf-life abaixo do exigido pelo cliente |
| Preco_Unitario_Lista | Preço de tabela **vigente na data** (houve reajustes em mar/2025 e mar/2026) |
| Desconto_Comercial_Pct | Desconto de canal + contrato do cliente (%) |
| Desconto_Promocional_Pct | Desconto da promoção vigente (%) |
| Preco_Unitario_Liquido | Lista × (1 − descontos). Zero na bonificação |
| Valor_Bruto | Qtd_Vendida × Preço de lista (na bonificação é o valor de referência da mercadoria) |
| Valor_Liquido | Qtd_Vendida × Preço líquido |
| ID_Promocao | Promoção vigente no item (vazio se não houver) |
| Motivo_Devolucao | Preenchido só nas devoluções |

Regra de consistência: para `Venda` e `Bonificação`, `Qtd_Pedida = Qtd_Vendida + Qtd_Cortada`.

### `f_Forecast.csv` — 1 linha por mês x SKU (forecast oficial, compatível com o `kpis.py`)
É a versão **Consenso, lag 1** (feita no ciclo do mês anterior), somada para todos os canais. Só contém meses já fechados (mai/2024 a set/2026).

| Coluna | Descrição |
|---|---|
| Data_Mes | Mês previsto (primeiro dia do mês) |
| ID_Produto | SKU |
| Qtd_Prevista | Forecast consenso lag 1 (o oficial, que o `kpis.py` já usa) |
| Qtd_Prevista_Estatistica | Forecast estatístico lag 1 |
| Qtd_Prevista_Comercial | Forecast do time comercial lag 1 |
| Ciclo_SOP | Ciclo em que a previsão foi feita |

### `f_Forecast_Historico.csv` — snapshots de todos os ciclos (~37 mil linhas)
Nível: **Ciclo_SOP x Data_Mes x SKU x Canal x Versão**.

| Coluna | Descrição |
|---|---|
| Ciclo_SOP | Mês em que o forecast foi feito (1º dia) |
| Data_Mes | Mês previsto |
| Lag | Meses entre o ciclo e o mês previsto (0 = mesmo mês). Lags 0–3 em todos os ciclos, e 0–5 no último ciclo (out/2026) |
| ID_Produto, Canal | Nível de planejamento |
| Versao | `Estatístico` (modelo sobre o histórico de **faturamento**), `Comercial` (estatístico + otimismo + promoções já cadastradas + metas de lançamento) e `Consenso` (decisão final do S&OP) |
| Qtd_Prevista | Unidades, arredondadas para caixa fechada |

Para filtrar o forecast oficial do mês: `Versao = 'Consenso' AND Lag = 1`. Os ciclos de out/2026 em diante não têm realizado, porque são o plano futuro.

### `f_Budget.csv` — orçamento anual (2025 e 2026)
Feito em novembro do ano anterior, por **mês x SKU x Canal**: `Ano`, `Data_Mes`, `ID_Produto`, `Canal`, `Qtd_Budget`, `Valor_Budget` (R$ líquido estimado). Serve para comparar Realizado x Forecast x Budget (gap de orçamento).

### `f_Promocoes.csv` — calendário promocional
Nível: **promoção x cliente x SKU** (uma campanha `ID_Promocao` pode ter várias linhas).

| Coluna | Descrição |
|---|---|
| ID_Promocao | Código da campanha |
| ID_Cliente, ID_Produto | Onde a ação acontece |
| Mecanica | Desconto em tabela, Encarte/Tabloide, Ponta de gôndola, Leve 3 Pague 2, Aniversário da rede, Black Friday, Ação de sell-out (verba) |
| Data_Cadastro | Quando a ação foi cadastrada. Ações cadastradas depois do ciclo não entram no forecast daquele ciclo |
| Data_Inicio, Data_Fim | Vigência |
| Desconto_Pct | Desconto concedido (%) |
| Uplift_Planejado_Pct | Aumento de volume esperado pelo comercial (%). O uplift **real** é diferente e precisa ser medido nas vendas |
| Bonificacao_Pct | % de mercadoria bonificada na ação |
| Status | Executada ou Cancelada (ações canceladas não geram aumento de venda) |

### `f_Estoque.csv` — 1 linha por mês x SKU x CD
| Coluna | Descrição |
|---|---|
| Data_Mes | Mês |
| ID_Produto, ID_CD | Chaves |
| Estoque_Inicial | Unidades no início do mês |
| Entradas_Producao | Recebimentos da fábrica (lotes semanais planejados a partir do forecast) |
| Saidas_Venda, Saidas_Bonificacao | Expedições faturadas |
| Perdas_Vencimento | Descarte por vencimento (principalmente refrigerados) |
| Perdas_Obsolescencia | Baixa de estoque de SKU descontinuado |
| Estoque_Final | Inicial + Entradas − Saídas − Perdas |
| Qtd_Cortada_Falta_Estoque | Unidades pedidas e não atendidas por falta de produto |
| Dias_Com_Ruptura | Dias do mês com algum corte por falta de estoque |

---

## ⚠️ Armadilhas (iguais às da vida real)

1. **Demanda ≠ venda faturada.** Quando falta produto, o faturado fica abaixo do que o cliente pediu. Para medir acurácia de **demanda**, use `Qtd_Pedida` das linhas `Venda`. Quem medir pelo faturado subestima o erro nos meses de ruptura.
2. **O `kpis.py` atual soma tudo** em `Qtd_Vendida`: venda, bonificação e devolução (negativa). Vale decidir e documentar o que entra no "Realizado".
3. **Granularidade diferente:** o forecast está em SKU x Canal x Mês, e as vendas em cliente x dia. Juntar sem agregar antes duplica valores.
4. **Data de pedido x data de faturamento:** a escolha muda o mês de vários pedidos de fim de mês.
5. **Meses sem venda:** SKUs descontinuados e sazonais têm forecast com realizado zero (erro de 100%), e lançamentos têm realizado sem histórico.
6. **Preço muda no tempo:** `d_Produto.Preco_Lista` é o preço atual. Para histórico, use o preço da própria venda.
7. **Lag importa:** comparar o realizado com o forecast "mais recente" (lag 0) dá uma acurácia artificialmente boa.
8. **EAN e códigos são texto.** Leia como string para não perder formatação.

## 🧪 Versão "suja" (opcional)
Rode `python src/gerar_dados_simulados.py --com-problemas` para gerar também `Dados/_brutos_com_problemas/` com: linhas duplicadas, datas em dois formatos, SKU com zero à esquerda, código de produto inexistente no cadastro, preços faltando, nomes com espaços sobrando, canal em maiúsculas e região vazia. Serve para treinar a etapa de limpeza do ETL.

## 💡 Ideias de análise
- Acurácia, WMAPE e BIAS por **lag**, **canal**, **categoria**, **ABC/XYZ** e **executivo**
- **FVA (Forecast Value Add):** o consenso melhorou ou piorou o estatístico? E o comercial?
- **Fill rate** e cortes por motivo; relação entre BIAS negativo e ruptura
- Cobertura de estoque (dias) e perdas x BIAS positivo
- **Uplift real x planejado** das promoções e efeito pós-promoção
- Curva de lançamento (carga inicial x giro) e phase-in/phase-out
- Realizado x Forecast x **Budget**
- Positivação (clientes que compraram cada SKU no mês) e mix por cliente

---

<details>
<summary>🔍 Gabarito: eventos "plantados" na simulação (abra só depois de investigar)</summary>

| Quando | Evento | O que aparece nos dados |
|---|---|---|
| Todo ano | Sazonalidade | Sorvete com pico no verão e vale em jun/jul; maionese sobe em dezembro; congelados sobem na Quaresma; janeiro forte ("Veganuary") |
| set/2024 | Lançamento 112 (Maionese Alho) | Carga inicial alta e depois normalização |
| fev–abr/2025 | Reajuste de preço (+7%) em mar/2025 | Distribuidores e atacarejo antecipam compras em fevereiro; queda em março/abril; BIAS positivo |
| fev/2025 | Lançamento 119 (Frango Empanado) | Meta comercial otimista, BIAS positivo nos primeiros meses |
| mar/2025 | Lançamento 109 (Chocolate 200ml) | Canibaliza o 108 |
| jun/2025 | Descontinuação 110 (Baunilha 1L) | Forecast ainda positivo nos ciclos antigos; baixa por obsolescência |
| jul–ago/2025 | Falta de proteína no fornecedor do 103 | Produção reduzida, cortes por falta de estoque e forecast estatístico "contaminado" pela venda censurada |
| jul/2025 e set/2025 | Novos clientes (Litoral Capixaba e Quick Commerce) | Rampa de entrada |
| out/2025 | Cliente C035 perdido | Queda e depois zero |
| out/2025 | Lançamento 122 (Smash) | Canibaliza o 103 |
| fev–mar/2026 | Troca 120 → 121 (Linguiça) | Phase-in/phase-out |
| mar/2026 | Novo CD do Max Economia na BA (C022) e reajuste (+4% a +6%) | Rampa do cliente e nova antecipação de compra |
| abr/2026 em diante | Concorrente novo em Bebidas | Queda de ~9% que o forecast demora a captar (BIAS positivo) |
| abr/2026 e jun/2026 | Lançamentos 130 (Iogurte 500g) e 115 (Chipotle) | Pouco histórico, erro alto |
| nov/2024 em diante | SKU sazonal 124 (só nov–mar) | Primeira temporada com forte ruptura (sem histórico para planejar). Nas seguintes, o comercial planeja pelo pedido do ano anterior. Sobra estoque parado de abril a outubro |
| Nov | Black Friday no e-commerce | Picos de curto prazo |

</details>
