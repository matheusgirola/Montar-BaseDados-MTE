# Ponto de retomada — 2026-09-03

Estado da sessão mais recente. **Este arquivo é descartável** — lições,
bugs e achados de dado moram no `CLAUDE.md`; aqui fica só "onde paramos" e
"o que fazer a seguir". Reescreva-o na próxima retomada em vez de acumular
histórico.

## Estado

| | |
|---|---|
| Parquet principal | `E:\pdet\10_parquet` — vínculos e estabelecimentos, **2010-2025, todas as UFs**, 875 arquivos, 44,7 GB |
| Vínculos | **1.178.045.148 linhas** |
| `E:\pdet\03_meta\conversao.csv` | **284 unidades, todas `ok`** |
| Parquet do Legado | `E:\pdet\10_parquet_legado` — 2023 inteiro, 2019 só Centro-Oeste |
| Banco | `C:\pdet\pdet.duckdb` (principal) e `C:\pdet\pdet_legado.duckdb` |
| Checagens | **14 de 14 rodaram**, nenhuma pulada |
| Cubos | **materializados** — 7 cubos, 2010-2025, rollup fecha em zero |
| Disco livre | C: 49 GB / E: 750 GB |

**A fase 3 está inteira.** `criar`, `checar`, `codigos`, `agregar` e
`consulta` todos rodados sobre a base nacional. Não há passo de construção
pendente — ver `CLAUDE.md` seção 4 para o detalhe de cada achado (§4.1 a
§4.8) e seção 6 para as divergências já fechadas.

## O que fazer em seguida, nesta ordem

**1. Usar o banco.** As 21 consultas nomeadas de `sql/consultas.sql` rodam
sobre os cubos, em frações de segundo:

```powershell
uv run python pdet_banco.py --banco C:\pdet\pdet.duckdb consulta --nome estoque_brasil
```

**2. Completar os 40 códigos que faltam.** Listados em
`C:\pdet\log\codigos_observados.csv`. Quase todos são de 2023 em diante —
o MTE não publicou layout novo. Maior buraco: `categoria_trabalhador` (22
códigos, 262 milhões de linhas). Se aparecer layout novo, procedimento em
`CLAUDE.md` seção 5.

**3. Se a pasta `Legado` de 2019 for necessária, peça os arquivos ao MTE.**
Os do FTP estão corrompidos na origem (`CLAUDE.md` §4.3) e rebaixar não
resolve.

**Para refazer os cubos**, se algum dia precisar — `--ano X` apaga e
reescreve só aquele ano, o resto fica intacto:

```powershell
powershell -File C:\pdet\agregar_lento.ps1 2019 2020 2021
```

Detalhe do porquê 2023+ usa memória diferente em `CLAUDE.md` §4.7.

## Como rodar

Runbook completo em `docs/COMO-RODAR-BANCO.txt`. A única armadilha
específica desta máquina: `--meta` precisa de uma pasta só, e o
`conversao.csv` bom mora em `E:\pdet\03_meta`, não no repositório.
`C:\pdet\meta` já está montada certa — não aponte `--meta` para a raiz
do projeto.

## Energia — comandos rápidos

Histórico completo dos dois incidentes em `CLAUDE.md` §4.6. Aqui só os
comandos que precisam ser refeitos **a cada logon**, porque a política
corporativa reseta tudo:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 `
    48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setactive SCHEME_CURRENT
```

E o vigia, antes de qualquer etapa longa no HD externo:

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-WindowStyle','Hidden', `
    '-ExecutionPolicy','Bypass','-File','C:\pdet\watchdog.ps1' -WindowStyle Hidden
```

Para conferir se está rodando, **exclua o próprio `$PID`** — senão o
comando se conta a si mesmo e diz "1 vigia" com zero rodando:

```powershell
$meu = $PID
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.ProcessId -ne $meu -and $_.CommandLine -like '*watchdog.ps1*' }
```

Para qualquer rodada longa (conversão ou `agregar`), use os scripts que já
aplicam o consumo reduzido — não chame `pdet_parquet.py`/`pdet_banco.py`
direto no HD externo:

- `C:\pdet\resume_vinc.ps1` — conversão, uma unidade por invocação
- `C:\pdet\agregar_lento.ps1` — cubos, um ano por invocação

## Backups

Convenção: antes de editar `pdet_parquet.py`, `pdet_banco.py`,
`dicionarios/dic_rais.csv`, `dicionarios/dim_codigos.csv`, `CLAUDE.md` ou
`RETOMAR.md`, copie para `C:\pdet\<nome>.bak`
(sufixo numerado se já houver um `.bak`). Os backups ficam só em `C:\pdet`,
fora do repositório — não commitar.
