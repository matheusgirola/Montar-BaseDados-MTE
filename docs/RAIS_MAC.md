# RAIS_MAC.md — rodando o pipeline PDET no macOS

Notas específicas do ambiente **Mac**. O `CLAUDE.md` descreve a máquina
Windows corporativa original; este arquivo cobre só o que muda aqui, mais o
que foi descoberto rodando o pipeline localmente.

> Achados que valem para **qualquer** ambiente (formato dos dados, estrutura
> do FTP, esquemas da RAIS) ficam no `CLAUDE.md`, não aqui.

---

## 1. A máquina

| | Windows (original) | Mac (aqui) |
|---|---|---|
| CPU | i5-13400 (10 núcleos) | Apple M2 (8 núcleos) |
| RAM | 16 GB | **8 GB** |
| Disco local livre | ~477 GB SSD | ~50 GB |
| Dados | `E:\pdet` (HD externo) | `/Volumes/HD E. 500GB/pdet` (exFAT, 466 GB) |
| Shell | PowerShell 5.1 | zsh (padrão) / bash 3.2 |
| Launcher | `pdet.ps1` | `pdet.sh` |

**A RAM é o número que mais importa.** Os defaults do projeto foram
calibrados para 16 GB: `pdet_parquet.py --memoria` e `pdet_banco.py
--memoria` valem 9 GB por padrão, acima da RAM física desta máquina. Aqui é
preciso passar `--memoria 4` (ou 5) explicitamente, senão o DuckDB é
autorizado a pedir mais memória do que existe.

O disco local também é apertado: 50 GB livres contra os ~477 GB do Windows.
Como o `pdet_parquet.py` faz staging no disco local (`--tmp`/`--estagio`),
convém manter o `--reserva-gb 20` e converter em lotes.

---

## 2. Três bugs do `pdet.sh` que só aparecem no Mac

Corrigidos em 2026-08-31.

### 2.1 `BASH_SOURCE[0]: parameter not set`

Rodar `zsh pdet.sh ...` faz o zsh interpretar um script bash. `BASH_SOURCE`
não existe no zsh e, com `set -u`, o script morre na linha 24.

Corrigido com `${BASH_SOURCE[0]:-$0}` e um `exec bash` quando o shell não é
bash — agora `zsh pdet.sh`, `sh pdet.sh` e `./pdet.sh` funcionam igual.

### 2.2 `diskutil info` num subdiretório — falha **silenciosa**

Este é o pior dos três, porque não imprime nada. `checar_drive()` fazia:

```sh
fs="$(diskutil info "$ponto" ...)"
```

com `$ponto` = `/Volumes/HD E. 500GB/pdet`. Mas o `diskutil` só aceita
**ponto de montagem ou device**, nunca um subdiretório: sai com código 1, a
atribuição herda esse código, e o `set -e` encerra o script sem mensagem.

O detalhe cruel: isso **funcionava na primeira execução**. Enquanto a pasta
`pdet/` não existia, o loop que sobe o caminho procurando um diretório
existente parava em `/Volumes/HD E. 500GB`, que é ponto de montagem. Só
depois que o primeiro download criou `pdet/` é que o bug passou a valer.

Corrigido resolvendo o device via `df -P` (campo 1, que nunca tem espaço)
antes de perguntar ao `diskutil`.

### 2.3 Array vazio no bash 3.2

O macOS ainda distribui **bash 3.2** (por licenciamento — o bash 4+ é GPLv3).
Nessa versão, expandir um array vazio sob `set -u` é erro:

```
A=(); printf '%s\n' "${A[@]}"   # bash 3.2: "A[@]: unbound variable"
```

Quebraria em `./pdet.sh baixar` sem flags adicionais. Corrigido testando
`${#PASS[@]}` antes de expandir.

---

## 3. Interpretador: o `pdet.sh` não achava o `.venv`

O ambiente do projeto é o `.venv/` da raiz, criado pelo **uv 0.11.6**
(`uv sync`, a partir do VS Code). Ele usa o Python do Anaconda como base
(`home = /opt/anaconda3/bin` no `pyvenv.cfg`), o que confunde: o
`/opt/anaconda3/bin/python3` "cru" **não** tem as dependências, o `.venv`
tem.

| pacote | `/opt/anaconda3/bin/python3` | `.venv/bin/python` (uv) |
|---|---|---|
| duckdb | ausente | 1.5.5 |
| py7zr | ausente | 1.1.3 |
| pyarrow | 20.0.0 | 25.0.1 |
| pandas | 2.1.4 | 3.0.5 |

O `pdet.sh` escolhia o primeiro `python3` do PATH, que aqui é o Anaconda.
`baixar` funcionava assim (o `pdet_download.py` só usa a biblioteca padrão),
mas `pdet_parquet.py` e `pdet_banco.py` teriam morrido no `import duckdb`.

Corrigido: a busca agora começa por `$RAIZ/.venv/bin/python` e
`$VIRTUAL_ENV/bin/python`, caindo no PATH só se nenhum existir. O launcher
imprime qual interpretador escolheu — vale conferir essa linha.

Fora do launcher, tanto faz `uv run python script.py` ou
`.venv/bin/python script.py`.

## 4. 7-Zip

Não vinha instalado. `brew install sevenzip` instala o binário como **`7zz`**
(não `7z`) em `/opt/homebrew/bin`. Tanto o `pdet.sh` quanto o `achar_7z()`
do `pdet_parquet.py` já procuram por `7zz`, então funciona sem configuração.
Sem ele o fallback é o `py7zr`, bem mais lento.

## 5. exFAT: os arquivos `._` (AppleDouble) — o pior problema do Mac

O exFAT não guarda atributos estendidos, então o macOS grava um sidecar
`._NOME.ext` de 4 KB ao lado de cada arquivo. Eles **casam com os globs do
pipeline**. Numa rodada só, apareceram 25 no `00_raw` e **166 na árvore
Parquet**.

**No `.7z` é ruído.** `pdet_parquet.py` e `pdet_cabecalhos.py` listavam com
`rglob("*")` filtrando por sufixo e tentariam sondar os sidecars; caem em
"ignorado", poluindo o relatório. Ambos passaram a descartar nomes começando
com `._`.

**No Parquet é bloqueador.** O `pdet_banco.py criar` monta as views com
`read_parquet('.../**/*.parquet')`, que casa com `._u40c6....parquet`, e o
DuckDB morre:

```
Invalid Input Error: No magic bytes found at end of file
'.../ano=2014/uf=PI/._u40c6454200_....parquet'
```

Não é aviso: derruba a etapa inteira. Corrigido trocando o glob para
`**/[!.]*.parquet`, que descarta nomes iniciados por ponto e é inócuo em
Linux e Windows. Verificado: com o glob antigo o `read_parquet` falha; com o
novo lê as 19 unidades sem erro.

Mesmo com o glob defensivo, vale limpar de tempos em tempos:

```bash
find "/Volumes/HD E. 500GB/pdet" -name "._*" -delete
```

## 6. exFAT: sem journaling

O `pdet.sh` já avisa. Vale repetir porque **este HD desconecta sozinho por
problemas de energia**: em exFAT, uma queda no meio de uma gravação pode
corromper o diretório inteiro, não só o arquivo aberto. O `manifesto.csv` e o
`conversao.csv` tornam os dois estágios retomáveis, então o custo de uma
queda é reprocessar a unidade em andamento — desde que a tabela de alocação
sobreviva. APFS resolveria, mas exige reformatar.

---

## 7. Cuidados operacionais neste ambiente

- **Antes de qualquer etapa longa**, confirmar que o drive está montado:
  `ls "/Volumes/HD E. 500GB/pdet"`.
- **Depois de uma queda**, rodar `pdet_verifica.py` antes de converter: o
  `.7z` truncado passa no `py7zr.test()` (que só confere o CRC do cabeçalho)
  e só aparece na descompactação completa.
- `caffeinate` (usado pelo `pdet.sh`) impede o Mac de dormir, mas **não
  impede o HD de desmontar** por falta de energia no barramento USB.
- Converter em lotes por ano, não tudo de uma vez: com 50 GB de disco local,
  o staging de um ano inteiro do Brasil não cabe.

---

## 8. A rodada de 2026-08-31: o que aconteceu de fato

Sequência completa sobre 19 unidades (Nordeste 2018-2025, PI 2013-2017,
Brasil 2025): download -> Parquet -> verificação -> `criar` -> `checar`.

### Desempenho

O M2 com o `7zz` é bem mais rápido do que o esperado: **59 GB
descomprimidos convertidos em ~11 minutos**, com picos de 90 MB/s. As
unidades maiores (SP 2025, 6,4 GB) levaram ~87 s cada. Os `--memoria 4
--threads 6` foram suficientes; não houve pressão de memória nem spill.

O gargalo é a **rede**, não a máquina: o download de 3 GB rodou a ~1,6 MB/s
e levou ~30 minutos, quase o triplo do tempo da conversão inteira.

### A desconexão do HD — o que quebrou e o que não quebrou

O HD desmontou às 19:20:48, no meio da unidade 12 de 14 (Nordeste 2021).
Reconectado manualmente às 19:21:33.

**Não houve perda de dado nenhuma.** O que salvou:

- O `pdet_parquet.py` grava no **disco local** e só move para o HD quando a
  unidade inteira termina. A unidade interrompida não deixou nem um Parquet
  parcial na árvore final, nem sobra no estágio.
- O `conversao.csv` sobreviveu íntegro (16 unidades, todas `ok`), então o
  retomar reprocessou exatamente as 3 que faltavam.
- Verificação posterior com descompactação completa: **19/19 íntegros, 0
  corrompidos, 0 com tamanho divergente.**

**O que quebra feio é o erro em si.** O traceback tem quatro exceções
encadeadas e a última é enganosa:

```
PermissionError: [Errno 13] Permission denied: '/Volumes/HD E. 500GB'
```

Isso **não** é problema de permissão: quando o volume some, o macOS deixa
`/Volumes` como diretório de root, e o `mkdir` do checkpoint bate nele. Ao
ver `Permission denied` em `/Volumes/...`, o primeiro reflexo deve ser
conferir se o drive está montado, não mexer em permissão.

### Recomendação para rodadas longas

Antes de qualquer backfill grande, vale ter um vigia do ponto de montagem
rodando em paralelo — descobrir a desconexão no segundo em que acontece é
muito melhor do que descobrir uma hora depois pelo traceback:

```bash
while true; do
  [ -d "/Volumes/HD E. 500GB/pdet" ] || echo "HD sumiu em $(date +%H:%M:%S)"
  sleep 5
done
```

### Cuidado: não editar o `pdet.sh` enquanto ele roda

O bash lê o script **incrementalmente**, por deslocamento de byte. Editar o
arquivo no meio da execução desloca o resto e o shell passa a ler lixo — na
rodada de 31/08 isso produziu um `syntax error near unexpected token 'done'`
depois que o download já tinha terminado. Não houve dano porque o Python já
tinha saído, mas numa edição mais cedo teria interrompido o download.

### Resultado

| | |
|---|---|
| Unidades convertidas | 19/19 `ok` |
| Linhas | 185.068.075 |
| Parquet gerado | 8,6 GB |
| Integridade dos `.7z` | 19/19 íntegros |
| Checagens do banco | 11 de 12 rodaram; a 12ª precisa de RAIS_ESTAB, que não foi baixada |

Os achados sobre **os dados** dessa rodada (a ruptura de 2023 na
remuneração, a faixa da checagem 10, o recorte regional só a partir de 2018)
estão no `CLAUDE.md`, porque valem em qualquer máquina.
