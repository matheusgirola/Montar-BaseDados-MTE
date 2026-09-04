# pdet — microdados RAIS/PDET (SEPLAN-PI)

Pipeline local para baixar, converter e consultar os microdados do
mercado de trabalho formal brasileiro — principalmente a **RAIS**
(Relação Anual de Informações Sociais), com **CAGED/Novo CAGED** também
mapeados — a partir do FTP do PDET/MTE
(`ftp://ftp.mtps.gov.br/pdet/microdados/`). Sem depender de nuvem: os
dados brutos e o Parquet convertido ficam num HD externo, e um banco
DuckDB local materializa os cubos analíticos.

O pipeline tem quatro fases — inventário do FTP, download, conversão
para Parquet e banco analítico — descritas em detalhe no
[`CLAUDE.md`](CLAUDE.md).

## Por onde começar

- **Rodar o pipeline:** [`docs/COMO-RODAR-BANCO.txt`](docs/COMO-RODAR-BANCO.txt)
  é o runbook operacional da fase 3 (o banco DuckDB) — comandos prontos
  para copiar. As fases 0-2 (inventário, download, conversão) estão
  documentadas nos próprios scripts (`--help`) e na seção 3 do
  `CLAUDE.md`.
- **Lições, bugs corrigidos e achados sobre os dados:**
  [`CLAUDE.md`](CLAUDE.md) é o documento canônico do projeto — toda
  descoberta sobre o formato da RAIS, todo bug de pipeline já corrigido e
  o estado atual da base moram lá.
- **Onde a última sessão parou:** [`RETOMAR.md`](RETOMAR.md) — descartável,
  reescrito a cada retomada.

## Estrutura do repositório

```
pdet_*.py, diagnostico_ftp.py, plano_rais.py   scripts do pipeline (fases 0-3)
pdet.ps1, pdet.sh, pdet-setup.ps1              launchers e setup de ambiente

dicionarios/   tabelas de referência editadas à mão (dic_rais.csv, dim_*.csv)
sql/           consultas.sql — consultas nomeadas sobre o banco
estado/        saída gerada pelo pipeline (inventário do FTP, sondagem de
               cabeçalhos, relatório de checagem) — versionada como
               snapshot documentado do estado do projeto
docs/          runbook operacional e notas de rodadas anteriores
```

## Ambiente

Gerenciado com [`uv`](https://docs.astral.sh/uv/) (`pyproject.toml` +
`uv.lock`):

```bash
uv sync
uv run python <script.py> <argumentos>
```

Detalhes de ambiente (máquina Windows corporativa, HD externo, proxy)
na seção 2 do [`CLAUDE.md`](CLAUDE.md).
