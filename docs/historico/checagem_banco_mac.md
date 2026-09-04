# Checagem do banco PDET

- Banco: `/Users/matheusgirola/pdet_tmp/pdet.duckdb`
- Parquet: `/Volumes/HD E. 500GB/pdet/10_parquet`
- Gerado em: 2026-08-31T22:32:50+00:00

## 1. cobertura_ano_uf

Linhas por ano e UF nos vinculos. Uma UF que despenca ou dispara de um ano para o outro e arquivo truncado ou duplicado, nao economia.

| ano | uf | linhas | variacao_pct |
|---|---|---|---|
| 2025 | AC | 266903 |  |
| 2018 | AL | 651772 |  |
| 2019 | AL | 643036 | -1.3 |
| 2020 | AL | 642411 | -0.1 |
| 2021 | AL | 691553 | 7.6 |
| 2022 | AL | 797410 | 15.3 |
| 2023 | AL | 868407 | 8.9 |
| 2024 | AL | 945438 | 8.9 |
| 2025 | AL | 1003312 | 6.1 |
| 2025 | AM | 1283550 |  |
| 2025 | AP | 262893 |  |
| 2018 | BA | 3076344 |  |
| 2019 | BA | 3004013 | -2.4 |
| 2020 | BA | 3021604 | 0.6 |
| 2021 | BA | 3210981 | 6.3 |
| 2022 | BA | 3576793 | 11.4 |
| 2023 | BA | 3823011 | 6.9 |
| 2024 | BA | 4029193 | 5.4 |
| 2025 | BA | 4331694 | 7.5 |
| 2018 | CE | 2030898 |  |
| 2019 | CE | 2047750 | 0.8 |
| 2020 | CE | 1996930 | -2.5 |
| 2021 | CE | 2108886 | 5.6 |
| 2022 | CE | 2344273 | 11.2 |
| 2023 | CE | 2525026 | 7.7 |
| 2024 | CE | 2736779 | 8.4 |
| 2025 | CE | 2936088 | 7.3 |
| 2025 | DF | 2413767 |  |
| 2025 | ES | 1858008 |  |
| 2025 | GO | 3177616 |  |
| 2018 | MA | 963863 |  |
| 2019 | MA | 964348 | 0.1 |
| 2020 | MA | 969936 | 0.6 |
| 2021 | MA | 1061682 | 9.5 |
| 2022 | MA | 1239429 | 16.7 |
| 2023 | MA | 1265961 | 2.1 |
| 2024 | MA | 1322842 | 4.5 |
| 2025 | MA | 1433509 | 8.4 |
| 2025 | MG | 9892998 |  |
| 2025 | MS | 1411238 |  |
| ... | cortado em 40 linhas | | |

## 2. particao_com_varias_origens

Cada particao ano/uf deveria receber dados de UMA unidade de conversao (um arquivo do FTP). Duas ou mais = provavel duplicacao de linhas.

Sem ocorrencias.

## 3. conferencia_com_manifesto

Linhas no Parquet x linhas registradas em conversao.csv. Divergencia significa arquivo movido, apagado ou convertido duas vezes.

Sem ocorrencias.

## 4. estoque_brasil

Vinculos ativos em 31/12, Brasil. E a serie que todo relatorio abre. Compare com a RAIS publicada: a ordem de grandeza e de 44 a 55 milhoes no periodo. Se estiver muito acima, ha duplicacao.

| ano | vinculos_declarados | ativos_3112 | pct_ativos |
|---|---|---|---|
| 2013 | 588703 | 444121 | 75.4 |
| 2014 | 614435 | 457730 | 74.5 |
| 2015 | 618060 | 460776 | 74.6 |
| 2016 | 586489 | 441693 | 75.3 |
| 2017 | 580445 | 453229 | 78.1 |
| 2018 | 11577913 | 8647237 | 74.7 |
| 2019 | 11524044 | 8548407 | 74.2 |
| 2020 | 11450066 | 8368329 | 73.1 |
| 2021 | 12190056 | 9030950 | 74.1 |
| 2022 | 13584961 | 9777008 | 72.0 |
| 2023 | 14577485 | 10482866 | 71.9 |
| 2024 | 15465156 | 10735689 | 69.4 |
| 2025 | 91710262 | 60691770 | 66.2 |

## 5. municipio_sem_ibge

Codigos de municipio que nao existem na tabela do IBGE. Um punhado e normal (municipios extintos, codigo ignorado); muitos indicam coluna trocada de posicao.

| ano | cod_mun | linhas |
|---|---|---|
| 2025 |  | 6208 |

## 6. uf_incoerente

A particao uf e derivada dos 2 primeiros digitos do municipio. Se nao bate com a UF do IBGE, a derivacao errou.

Sem ocorrencias.

## 7. cnae_sem_dicionario

Classes CNAE 2.0 sem correspondencia. Espera-se pouca coisa: codigos zerados e a CNAE 1.0 residual dos anos antigos.

| ano | cnae | linhas |
|---|---|---|
| 2025 | 99999 | 3581 |
| 2022 | 00977 | 2074 |
| 2022 | 00999 | 12 |
| 2024 | 99999 | 10 |

## 8. nulos_nas_colunas_chave

Percentual de nulos nas colunas que os relatorios usam. Um salto de 0% para 100% num ano e coluna que mudou de posicao no layout.

| ano | mun | sexo | instr | cnae | remun_dez | ativo | cbo |
|---|---|---|---|---|---|---|---|
| 2013 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2014 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2015 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2016 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2017 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2018 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2019 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2020 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2021 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2022 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2023 | 0.0 | 0.0 | 0.0 | 0.0 | 35.6 | 0.0 | 0.0 |
| 2024 | 0.0 | 0.0 | 0.0 | 0.0 | 37.0 | 0.0 | 0.0 |
| 2025 | 0.0 | 0.0 | 0.0 | 0.0 | 41.8 | 0.0 | 0.0 |

## 9. remuneracao_suspeita

Remuneracao de dezembro fora de faixa plausivel entre os ativos. Negativos ou valores estratosfericos denunciam decimal mal lido.

| ano | negativos | zerados | acima_1_milhao | mediana | maximo |
|---|---|---|---|---|---|
| 2013 | 0 | 18546 | 0 | 960.0 | 96758.62 |
| 2014 | 0 | 18147 | 0 | 1043.36 | 106532.0 |
| 2015 | 0 | 19970 | 0 | 1130.76 | 83939.91 |
| 2016 | 0 | 18551 | 0 | 1253.22 | 121680.0 |
| 2017 | 0 | 20541 | 0 | 1312.35 | 138740.0 |
| 2018 | 0 | 337107 | 0 | 1399.4 | 143066.2 |
| 2019 | 0 | 630982 | 0 | 1411.85 | 148204.44 |
| 2020 | 0 | 743853 | 0 | 1468.59 | 153669.65 |
| 2021 | 0 | 552931 | 0 | 1554.61 | 164463.27 |
| 2022 | 0 | 786601 | 0 | 1696.8 | 181696.08 |
| 2023 | 0 | 0 | 0 | 1928.48 | 196709.85 |
| 2024 | 0 | 0 | 0 | 2064.05 | 211705.79 |
| 2025 | 0 | 0 | 0 | 2740.56 | 227643.3 |

## 10. coerencia_com_salario_minimo

A mediana da remuneracao de dezembro dividida pelo salario minimo do ano deve ficar perto de 1,3 a 1,6. Fora disso, ha erro de escala.

| ano | mediana_nom | sal_min | mediana_em_sm |
|---|---|---|---|
| 2013 | 960.0 | 678.0 | 1.42 |
| 2014 | 1043.36 | 724.0 | 1.44 |
| 2015 | 1130.76 | 788.0 | 1.43 |
| 2016 | 1253.22 | 880.0 | 1.42 |
| 2017 | 1312.35 | 937.0 | 1.4 |
| 2018 | 1399.4 | 954.0 | 1.47 |
| 2019 | 1411.85 | 998.0 | 1.41 |
| 2020 | 1468.59 | 1045.0 | 1.41 |
| 2021 | 1554.61 | 1100.0 | 1.41 |
| 2022 | 1696.8 | 1212.0 | 1.4 |
| 2023 | 1928.48 | 1320.0 | 1.46 |
| 2024 | 2064.05 | 1412.0 | 1.46 |
| 2025 | 2740.56 | 1518.0 | 1.81 |

## 11. colunas_por_esquema

Quais colunas existem em quais anos. E o mapa do que da para comparar na serie historica e do que nao da.

| nome_canonico | esquemas |
|---|---|
| ano_chegada_brasil | 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| categoria_trabalhador | 2023-2025 |
| ibge_subsetor | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| ind_trab_intermitente | 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| ind_trab_parcial | 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| ind_vinculo_abandonado | 2023-2025 |
| remun_abril_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_agosto_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_fevereiro_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_janeiro_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_julho_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_junho_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_maio_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_marco_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_novembro_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_outubro_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| remun_setembro_nom | 2015-2015, 2016-2016, 2017-2017, 2018-2018, 2019-2019, 2020-2022, 2023-2025 |
| salario_contratual | 2018-2018 |
| tipo_salario | 2018-2018 |

## 12. estabelecimentos_por_ano

Estabelecimentos declarantes por ano. Serie estavel na casa dos 8 milhoes ate 2022.

> FALHOU: CatalogException: Catalog Error: Table with name estabelecimentos does not exist!
Did you mean "sqlite_master"?
