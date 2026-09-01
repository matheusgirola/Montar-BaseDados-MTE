# Fase 0 — Inventário do FTP do PDET

- Origem: `ftp://ftp.mtps.gov.br/pdet/microdados`
- Gerado em: 2026-08-31 15:14 -03
- Arquivos: **3.367**
- Volume comprimido: **79,6 GB**

## Volume por base

| base             |  arqs | comprimido | ~descompactado | ~parquet |     % |
|------------------|-------|------------|----------------|----------|-------|
| RAIS_VINCULOS    |    79 |    33,6 GB |       335,9 GB |  53,7 GB | 42,2% |
| RAIS_OUTRO       |   947 |    30,9 GB |       309,4 GB |  49,5 GB | 38,9% |
| NOVO_CAGED_MOV   |   274 |     8,7 GB |        87,3 GB |  14,0 GB | 11,0% |
| CAGED_ANTIGO     |   284 |     4,2 GB |        41,7 GB |   6,7 GB |  5,2% |
| RAIS_ESTAB       |    12 |     1,3 GB |        12,8 GB |   2,0 GB |  1,6% |
| NOVO_CAGED_OUTRO |   201 |   715,3 MB |         7,0 GB |   1,1 GB |  0,9% |
| NOVO_CAGED_FOR   |    78 |    95,3 MB |       953,3 MB | 152,5 MB |  0,1% |
| AUXILIAR_DOC     | 1.416 |    47,0 MB |       470,4 MB |  75,3 MB |  0,1% |
| NOVO_CAGED_EXC   |    76 |     7,8 MB |        77,8 MB |  12,4 MB |  0,0% |

> Estimativas usam fatores 10.0x (descompactação) e 1.6x (parquet zstd, todas as colunas). São chutes: meça 1 arquivo real na Fase 1 e recalibre com `--fator-descompacta` / `--fator-parquet`.

## Volume por ano

| ano  | arqs | comprimido | ~parquet |
|------|------|------------|----------|
| 1985 |   28 |   301,5 MB | 482,3 MB |
| 1986 |   28 |   350,1 MB | 560,1 MB |
| 1987 |   28 |   370,5 MB | 592,8 MB |
| 1988 |   28 |   375,3 MB | 600,4 MB |
| 1989 |   30 |   389,6 MB | 623,4 MB |
| 1990 |   30 |   392,0 MB | 627,3 MB |
| 1991 |   29 |   375,2 MB | 600,3 MB |
| 1992 |   30 |   345,8 MB | 553,3 MB |
| 1993 |   31 |   349,0 MB | 558,5 MB |
| 1994 |   30 |   449,8 MB | 719,7 MB |
| 1995 |   30 |   490,3 MB | 784,5 MB |
| 1996 |   30 |   511,8 MB | 818,9 MB |
| 1997 |   30 |   513,3 MB | 821,3 MB |
| 1998 |   29 |   523,3 MB | 837,2 MB |
| 1999 |   28 |   660,9 MB |   1,0 GB |
| 2000 |   29 |   701,8 MB |   1,1 GB |
| 2001 |   29 |   743,6 MB |   1,2 GB |
| 2002 |   29 |   763,4 MB |   1,2 GB |
| 2003 |   29 |   817,4 MB |   1,3 GB |
| 2004 |   29 |   866,5 MB |   1,4 GB |
| 2005 |   29 |   941,3 MB |   1,5 GB |
| 2006 |   29 |   992,7 MB |   1,6 GB |
| 2007 |   41 |     1,4 GB |   2,2 GB |
| 2008 |   41 |     1,5 GB |   2,4 GB |
| 2009 |   41 |     1,5 GB |   2,4 GB |
| 2010 |   52 |     1,7 GB |   2,7 GB |
| 2011 |   52 |     1,8 GB |   2,9 GB |
| 2012 |   52 |     1,9 GB |   3,0 GB |
| 2013 |   53 |     1,9 GB |   3,1 GB |
| 2014 |   52 |     2,0 GB |   3,1 GB |
| 2015 |   54 |     2,8 GB |   4,5 GB |
| 2016 |   54 |     2,8 GB |   4,5 GB |
| 2017 |   55 |     2,8 GB |   4,4 GB |
| 2018 |   32 |     2,9 GB |   4,6 GB |
| 2019 |   42 |     5,3 GB |   8,5 GB |
| 2020 |  348 |     7,3 GB |  11,7 GB |
| 2021 |  137 |     4,8 GB |   7,7 GB |
| 2022 |   45 |     3,5 GB |   5,6 GB |
| 2023 |   61 |     9,8 GB |  15,6 GB |
| 2024 |   55 |     6,9 GB |  11,1 GB |
| 2025 |   46 |     4,6 GB |   7,4 GB |
| 2026 |   21 |   373,5 MB | 597,6 MB |

**Custo de escopo — últimos N anos (em parquet):**

| escopo               | ~parquet acumulado |
|----------------------|--------------------|
| 1 ano(s) (até 2026)  |           597,6 MB |
| 3 ano(s) (até 2024)  |            19,1 GB |
| 5 ano(s) (até 2022)  |            40,3 GB |
| 10 ano(s) (até 2017) |            77,2 GB |
| 15 ano(s) (até 2012) |            95,4 GB |
| 20 ano(s) (até 2007) |           108,1 GB |
| 42 ano(s) (até 1985) |           127,2 GB |

## RAIS por recorte geográfico

| recorte      | arqs | comprimido |   ~parquet |
|--------------|------|------------|------------|
| SP           |   45 |    19,7 GB |    31,6 GB |
| MG_ES_RJ     |   12 |     6,9 GB |    11,0 GB |
| SUL          |   12 |     6,5 GB |    10,4 GB |
| NORDESTE     |   12 |     5,2 GB |     8,3 GB |
| MG           |   33 |     3,1 GB |     5,0 GB |
| CENTRO_OESTE |   12 |     3,1 GB |     4,9 GB |
| RJ           |   33 |     2,8 GB |     4,5 GB |
| RS           |   33 |     2,1 GB |     3,3 GB |
| PR           |   33 |     1,9 GB |     3,1 GB |
| NORTE        |   12 |     1,7 GB |     2,7 GB |
| SC           |   33 |     1,4 GB |     2,3 GB |
| BA           |   33 |     1,2 GB |     1,9 GB |
| PE           |   33 |   868,0 MB |     1,4 GB |
| GO           |   33 |   848,0 MB |     1,3 GB |
| CE           |   33 |   718,2 MB |     1,1 GB |
| DF           |   33 |   631,8 MB | 1.011,0 MB |
| ES           |   33 |   573,9 MB |   918,3 MB |
| PA           |   32 |   543,0 MB |   868,9 MB |
| MT           |   33 |   475,4 MB |   760,6 MB |
| MS           |   33 |   385,6 MB |   617,0 MB |
| AM           |   33 |   315,7 MB |   505,1 MB |
| RN           |   33 |   303,4 MB |   485,4 MB |
| MA           |   32 |   295,6 MB |   472,9 MB |
| PB           |   33 |   287,8 MB |   460,4 MB |
| AL           |   33 |   253,7 MB |   406,0 MB |
| SE           |   33 |   203,2 MB |   325,1 MB |
| PI           |   33 |   189,3 MB |   303,0 MB |
| RO           |   33 |   183,7 MB |   293,9 MB |
| TO           |   29 |   120,6 MB |   193,0 MB |
| AC           |   33 |    58,8 MB |    94,0 MB |
| AP           |   33 |    53,8 MB |    86,1 MB |
| RR           |   33 |    36,0 MB |    57,5 MB |

> Se o foco é PI/Nordeste, a linha NORDESTE é o seu escopo mínimo viável.

## Por extensão

| ext  |  arqs |    bytes |
|------|-------|----------|
| 7z   | 1.938 |  79,0 GB |
| rds  |     1 | 336,8 MB |
| zip  |     5 | 199,3 MB |
| xls  | 1.401 |  45,0 MB |
| xlsx |     4 |   1,1 MB |
| pdf  |     9 | 977,2 KB |
| htm  |     2 | 538,3 KB |
| txt  |     7 |   1,8 KB |

## Decisões que este inventário destrava

1. **Escopo temporal**: quantos anos de RAIS cabem no orçamento de disco?
2. **Escopo geográfico**: só NORDESTE ou Brasil inteiro?
3. **Colunas**: se o parquet completo já couber, não vale a pena montar versão *slim*.
4. **Ordem do backfill**: comece pelo ano mais recente e caminhe para trás.
5. **Tempo de download**: divida o volume pela sua banda real — é isso que define se o backfill leva 1 noite ou 1 semana.
