# Ponto de retomada — 2026-08-31, 22:50

Sessão encerrada a pedido, no meio da fila. **Nada foi perdido**: os dois
estágios são retomáveis por checkpoint.

## Estado

| | |
|---|---|
| `manifesto.csv` (download) | 48 arquivos, todos `ok` |
| `conversao.csv` (Parquet) | 25 unidades, todas `ok` — **214.086.784 linhas** |
| Parquet principal | `/Volumes/HD E. 500GB/pdet/10_parquet` |
| Banco DuckDB | `/Users/matheusgirola/pdet_tmp/pdet.duckdb` |
| Disco local livre | 49 GB / HD externo | 438 GB |

Cobertura convertida: RAIS_VINCULOS Nordeste 2018-2025, PI 2013-2017,
Brasil 2025, mais as 6 anomalias (AC/AP 2014, MT 2011, RS 2012, SP 2015,
CE 2016).

## Falta baixar: 1 arquivo

```
/pdet/microdados/RAIS/2023/Legado/RAIS_VINC_PUB_SUL.7z   (618 MB)
```

Já existe um `.part` com ~300 MB baixados. **Não apagar** — o download
retoma por FTP REST de onde parou.

```bash
./pdet.sh baixar --base RAIS_VINCULOS --ano 2023 --incluir-legado
```

## Bônus não planejado

O comando do Legado usou `--ano 2019 --ano 2023`, que também trouxe as
**definitivas** de 2019 e 2023 para todas as regiões (antes só havia
Nordeste). Ou seja: dá para comparar 2019 e 2023 **Brasil inteiro** contra
os números oficiais usando a versão definitiva, além do Legado.

## Retomar

Os dois scripts estão prontos e são idempotentes — podem ser rodados de
novo do começo, que pulam o que já foi feito:

```bash
/Users/matheusgirola/pdet_tmp/sequencia.sh   # Legado -> arvore separada -> compara com oficial
/Users/matheusgirola/pdet_tmp/vizinhos.sh    # anos vizinhos das anomalias -> series
```

O `vizinhos.sh` espera o `sequencia.sh` sair. Há também
`/Users/matheusgirola/pdet_tmp/watchdog.sh`, que mata o pipeline se o HD
sumir por 120 s.

**Importante:** o Legado tem de ir para `10_parquet_legado`, com
`--manifesto .../03_meta/conversao_legado.csv`. Convertê-lo na árvore
principal criaria duas origens para as partições 2019 e 2023 — exatamente a
duplicação que a checagem 2 detecta. Os scripts já fazem isso certo.

## As duas perguntas em aberto

**1. As versões explicam 2019 e 2023?** Hipótese: o FTP serve hoje uma
vintage revisada, diferente da usada nas publicações oficiais. Teste: o
Legado convertido deve bater **47.554.211** (2019) e **54.706.385** (2023).
Doze outros anos já batem dígito por dígito com o oficial.

**2. As "quedas verticais" são reais?** Já convertidas as unidades de MT
2011, RS 2012, SP 2015 e CE 2016, mas **falta baixar os anos vizinhos** —
sem eles não há com o que comparar. É o que o `vizinhos.sh` faz (1,6 GB).

**Já respondida:** a anomalia "AC e AP idênticos em 2014" **não existe** —
AC 191.604 vs AP 184.811, e os `.7z` têm tamanhos diferentes.

## Nota de rede

A velocidade caiu de 1,6 MB/s (18h) para 0,88 MB/s (22h45). Se estiver
lento de novo, é o servidor do MTE, não a máquina.
