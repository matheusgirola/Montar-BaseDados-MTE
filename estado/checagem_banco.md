# Checagem do banco PDET

- Banco: `C:\pdet\pdet.duckdb`
- Parquet: `E:\pdet\10_parquet`
- Gerado em: 2026-08-31T15:07:23+00:00

## Resumo

- Checagens executadas: **13 de 13**
- Nenhuma checagem foi pulada.

## 1. cobertura_ano_uf

Linhas por ano e UF nos vinculos. Uma UF que despenca ou dispara de um ano para o outro e arquivo truncado ou duplicado, nao economia.

| ano | uf | linhas | variacao_pct |
|---|---|---|---|
| 2010 | AC | 162148 |  |
| 2011 | AC | 172342 | 6.3 |
| 2012 | AC | 180152 | 4.5 |
| 2013 | AC | 181849 | 0.9 |
| 2014 | AC | 191604 | 5.4 |
| 2015 | AC | 191101 | -0.3 |
| 2016 | AC | 175733 | -8.0 |
| 2017 | AC | 177358 | 0.9 |
| 2018 | AC | 176867 | -0.3 |
| 2019 | AC | 167483 | -5.3 |
| 2020 | AC | 171258 | 2.3 |
| 2021 | AC | 186571 | 8.9 |
| 2022 | AC | 211988 | 13.6 |
| 2023 | AC | 244448 | 15.3 |
| 2024 | AC | 246955 | 1.0 |
| 2025 | AC | 266903 | 8.1 |
| 2010 | AL | 634668 |  |
| 2011 | AL | 682494 | 7.5 |
| 2012 | AL | 706221 | 3.5 |
| 2013 | AL | 717055 | 1.5 |
| 2014 | AL | 711143 | -0.8 |
| 2015 | AL | 694802 | -2.3 |
| 2016 | AL | 663297 | -4.5 |
| 2017 | AL | 650052 | -2.0 |
| 2018 | AL | 651772 | 0.3 |
| 2019 | AL | 643036 | -1.3 |
| 2020 | AL | 642411 | -0.1 |
| 2021 | AL | 691553 | 7.6 |
| 2022 | AL | 797410 | 15.3 |
| 2023 | AL | 868407 | 8.9 |
| 2024 | AL | 945438 | 8.9 |
| 2025 | AL | 1003312 | 6.1 |
| 2010 | AM | 828376 |  |
| 2011 | AM | 894498 | 8.0 |
| 2012 | AM | 927548 | 3.7 |
| 2013 | AM | 954426 | 2.9 |
| 2014 | AM | 960056 | 0.6 |
| 2015 | AM | 901719 | -6.1 |
| 2016 | AM | 810272 | -10.1 |
| 2017 | AM | 797800 | -1.5 |
| ... | CORTADO em 40 linhas - use `--limite 0` para o relatorio completo | | |

## 2. particao_com_varias_origens

Cada particao ano/uf deveria receber dados de UMA unidade de conversao (um arquivo do FTP). Duas ou mais = provavel duplicacao de linhas.

Sem ocorrencias.

## 3. anomalia_ano_uf

Recorte curto da checagem 1, so com o que destoa: contagem exatamente igual em UFs diferentes no mesmo ano (dois estados nao empatam na unidade - e o mesmo arquivo lido duas vezes) e variacao anual acima de 25% (queda = truncamento, salto = duplicacao).

| tipo | ano | uf | linhas | variacao_pct |
|---|---|---|---|---|
| variacao anual acima de 25% | 2022 | NI | 2338 | 14512.5 |
| variacao anual acima de 25% | 2023 | RR | 205291 | 30.8 |
| variacao anual acima de 25% | 2024 | NI | 16544 | 589.3 |
| variacao anual acima de 25% | 2025 | NI | 6208 | -62.5 |

## 4. conferencia_com_manifesto

Linhas no Parquet x linhas registradas em conversao.csv. Divergencia significa arquivo movido, apagado ou convertido duas vezes.

| ano | m_linhas | b_linhas | diferenca |
|---|---|---|---|
| 2010 | 387162097 | 66747302 | -320414795 |
| 2011 | 390734997 | 70971125 | -319763872 |
| 2012 | 384520723 | 73326485 | -311194238 |
| 2013 | 446691320 | 75400510 | -371290810 |
| 2014 | 454294711 | 76107279 | -378187432 |
| 2015 | 384080479 | 72175102 | -311905377 |
| 2016 | 374073687 | 67144598 | -306929089 |
| 2017 | 399817001 | 65655882 | -334161119 |
| 2018 | 181849776 | 66214692 | -115635084 |
| 2019 | 182395639 | 66667417 | -115728222 |
| 2020 | 181304845 | 65921194 | -115383651 |
| 2021 | 193707558 | 70521981 | -123185577 |
| 2022 | 216573754 | 78488470 | -138085284 |
| 2023 | 174342420 | 82966522 | -91375898 |
| 2024 | 181383490 | 87747220 | -93636270 |
| 2025 | 265085309 | 91710262 | -173375047 |

## 5. estoque_brasil

Vinculos ativos em 31/12, Brasil. E a serie que todo relatorio abre. Compare com a RAIS publicada: a ordem de grandeza e de 44 a 55 milhoes no periodo. Se estiver muito acima, ha duplicacao.

| ano | vinculos_declarados | ativos_3112 | pct_ativos |
|---|---|---|---|
| 2010 | 66747302 | 44068355 | 66.0 |
| 2011 | 70971125 | 46310631 | 65.3 |
| 2012 | 73326485 | 47458712 | 64.7 |
| 2013 | 75400510 | 48948433 | 64.9 |
| 2014 | 76107279 | 49571510 | 65.1 |
| 2015 | 72175102 | 48060807 | 66.6 |
| 2016 | 67144598 | 46060198 | 68.6 |
| 2017 | 65655882 | 46281590 | 70.5 |
| 2018 | 66214692 | 46631115 | 70.4 |
| 2019 | 66667417 | 46716492 | 70.1 |
| 2020 | 65921194 | 46236176 | 70.1 |
| 2021 | 70521981 | 48728871 | 69.1 |
| 2022 | 78488470 | 52790864 | 67.3 |
| 2023 | 82966522 | 55818007 | 67.3 |
| 2024 | 87747220 | 57800651 | 65.9 |
| 2025 | 91710262 | 60691770 | 66.2 |

## 6. municipio_sem_ibge

Codigos de municipio que nao existem na tabela do IBGE. Um punhado e normal (municipios extintos, codigo ignorado); muitos indicam coluna trocada de posicao.

| ano | cod_mun | linhas |
|---|---|---|
| 2024 |  | 16544 |
| 2025 |  | 6208 |
| 2023 |  | 2400 |

## 7. uf_incoerente

A particao uf e derivada dos 2 primeiros digitos do municipio. Se nao bate com a UF do IBGE, a derivacao errou.

Sem ocorrencias.

## 8. cnae_sem_dicionario

Classes CNAE 2.0 sem correspondencia. Espera-se pouca coisa: codigos zerados e a CNAE 1.0 residual dos anos antigos.

| ano | cnae | linhas |
|---|---|---|
| 2022 | 00977 | 6947 |
| 2025 | 99999 | 3581 |
| 2024 | 99999 | 3549 |
| 2023 | 99999 | 1594 |
| 2022 | 00999 | 280 |

## 9. nulos_nas_colunas_chave

Percentual de nulos nas colunas que os relatorios usam. Um salto de 0% para 100% num ano e coluna que mudou de posicao no layout.

| ano | mun | sexo | instr | cnae | remun_dez | ativo | cbo |
|---|---|---|---|---|---|---|---|
| 2010 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2011 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2012 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
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
| 2023 | 0.0 | 0.0 | 0.0 | 0.0 | 38.6 | 0.0 | 0.0 |
| 2024 | 0.0 | 0.0 | 0.0 | 0.0 | 40.0 | 0.0 | 0.0 |
| 2025 | 0.0 | 0.0 | 0.0 | 0.0 | 41.8 | 0.0 | 0.0 |

## 10. remuneracao_suspeita

Remuneracao de dezembro fora de faixa plausivel entre os ativos. Negativos ou valores estratosfericos denunciam decimal mal lido.

| ano | negativos | zerados | acima_1_milhao | mediana | maximo |
|---|---|---|---|---|---|
| 2010 | 0 | 1695036 | 0 | 946.17 | 76489.57 |
| 2011 | 0 | 1818097 | 0 | 1039.07 | 81750.0 |
| 2012 | 0 | 1897775 | 0 | 1161.07 | 93300.0 |
| 2013 | 0 | 1903450 | 0 | 1284.47 | 101697.0 |
| 2014 | 0 | 1956983 | 0 | 1394.85 | 108600.0 |
| 2015 | 0 | 2070722 | 0 | 1506.79 | 118163.52 |
| 2016 | 0 | 1953840 | 0 | 1637.25 | 132007.19 |
| 2017 | 0 | 1911771 | 0 | 1717.8 | 140419.58 |
| 2018 | 0 | 1855990 | 0 | 1771.35 | 143066.2 |
| 2019 | 0 | 3440756 | 0 | 1782.44 | 149705.42 |
| 2020 | 0 | 4045442 | 0 | 1824.65 | 156695.36 |
| 2021 | 0 | 2687580 | 0 | 1995.4 | 164977.19 |
| 2022 | 0 | 4463969 | 0 | 2138.77 | 181809.79 |
| 2023 | 0 | 0 | 0 | 2481.33 | 197933.66 |
| 2024 | 0 | 0 | 0 | 2647.1 | 211780.1 |
| 2025 | 0 | 0 | 0 | 2740.56 | 227643.3 |

## 11. coerencia_com_salario_minimo

A mediana da remuneracao de dezembro dividida pelo salario minimo do ano deve ficar perto de 1,3 a 1,6. Fora disso, ha erro de escala.

| ano | mediana_nom | sal_min | mediana_em_sm |
|---|---|---|---|
| 2010 | 946.17 | 510.0 | 1.86 |
| 2011 | 1039.07 | 545.0 | 1.91 |
| 2012 | 1161.07 | 622.0 | 1.87 |
| 2013 | 1284.47 | 678.0 | 1.89 |
| 2014 | 1394.85 | 724.0 | 1.93 |
| 2015 | 1506.79 | 788.0 | 1.91 |
| 2016 | 1637.25 | 880.0 | 1.86 |
| 2017 | 1717.8 | 937.0 | 1.83 |
| 2018 | 1771.35 | 954.0 | 1.86 |
| 2019 | 1782.44 | 998.0 | 1.79 |
| 2020 | 1824.65 | 1045.0 | 1.75 |
| 2021 | 1995.4 | 1100.0 | 1.81 |
| 2022 | 2138.77 | 1212.0 | 1.76 |
| 2023 | 2481.33 | 1320.0 | 1.88 |
| 2024 | 2647.1 | 1412.0 | 1.87 |
| 2025 | 2740.56 | 1518.0 | 1.81 |

## 12. colunas_por_esquema

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

## 13. estabelecimentos_por_ano

Estabelecimentos declarantes por ano. Serie estavel na casa dos 8 milhoes ate 2022.

| ano | estabelecimentos | rais_negativa | soma_vinculos_ativos |
|---|---|---|---|
| 2010 | 7617197 | 4213749 | 44068355 |
| 2011 | 7885436 | 4294820 | 46310631 |
| 2012 | 7900553 | 4204818 | 47458712 |
| 2013 | 8166010 | 4329239 | 48948433 |
| 2014 | 8240846 | 4290867 | 49571510 |
| 2015 | 8314306 | 4343198 | 48060807 |
| 2016 | 8205975 | 4284527 | 46060198 |
| 2017 | 8186588 | 4299139 | 46281590 |
| 2018 | 8082088 | 4215830 | 46631115 |
| 2019 | 7974757 | 4141470 | 46716492 |
| 2020 | 8196730 | 4416699 | 46236176 |
| 2021 | 8472949 | 4588756 | 48728871 |
| 2022 | 8453190 | 4004271 | 52790864 |
| 2023 | 11768420 | 7180937 | 55247863 |
| 2024 | 13186059 | 8465745 | 57061992 |
| 2025 | 13481949 | 8669124 | 59892402 |
