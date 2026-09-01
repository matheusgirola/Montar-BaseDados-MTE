# CLAUDE.md — Pipeline de microdados RAIS/PDET (SEPLAN-PI)

> Nota: você pediu "CLADE.md" — presumi que seja "CLAUDE.md" (o nome
> convencional para este tipo de arquivo de contexto). Se era outra coisa,
> me avise.
>
> Este arquivo foi montado a partir de três fontes: (1) as três conversas
> registradas neste projeto (04/08 e 13/08/2026), (2) os arquivos que estão
> hoje no Project Knowledge, e (3) a memória de longo prazo que o Claude
> mantém sobre este projeto. Onde as fontes divergiam, priorizei o que os
> arquivos realmente mostram e sinalizei a divergência — ver seção
> "Divergências a resolver" no final.

## 1. O que é este projeto

Matheus é analista de governo na SEPLAN (Secretaria de Planejamento do
Piauí) e está construindo, sozinho, uma base local de microdados do
mercado de trabalho formal brasileiro — principalmente a **RAIS** (Relação
Anual de Informações Sociais), com **CAGED/Novo CAGED** também mapeados —
a partir do FTP do PDET/MTE (`ftp://ftp.mtps.gov.br/pdet/microdados/`).
O objetivo final é alimentar relatórios comparativos anuais e séries
históricas de emprego formal, sem depender de nuvem.

**Ambiente:** máquina corporativa Windows (i5-13400, 16 GB RAM, SSD
~477 GB), HD externo de vários TB para os dados, sem privilégios de
administrador, proxy/TLS corporativo, e variável PATH gerenciada por
política que reseta a cada logon.

## 2. Ambiente técnico (como o projeto roda de fato)

- **Gerenciador de pacotes/ambiente:** `uv` (há `pyproject.toml` e
  `uv.lock` no projeto). O comando que sempre funciona, mesmo se `uv` não
  estiver no PATH:
  ```
  & "C:\Users\matheus.barbosa\.local\bin\uv.exe" sync
  & "C:\Users\matheus.barbosa\.local\bin\uv.exe" run python <script.py> ...
  ```
  Depois de abrir um PowerShell novo, o atalho de perfil (instalado pelo
  `pdet-setup.ps1`) deixa `uv sync` / `uv run ...` funcionarem direto.
  Os launchers (`pdet.ps1` / `pdet.sh`) também sabem resolver um
  **ambiente conda** (`-CondaEnv`, `CONDA_PREFIX` ativo, ou `-Conda` para
  a base) como intérprete alternativo — então os dois convivem no projeto.
- **Dependências principais** (`pyproject.toml`): `duckdb>=1.1`,
  `pyarrow>=17`, `py7zr>=1.0` (streaming de `.7z` sem precisar extrair
  o `.txt` inteiro — importante porque o de São Paulo passa de 50 GB),
  `pandas>=2.2`, `xlrd>=2.0` e `openpyxl>=3.1` (leitura dos layouts
  oficiais do MTE em `.xls`/`.xlsx`). Grupo opcional `notebook`
  (`jupyterlab`, `matplotlib`).
- **Caminhos de trabalho no HD externo:**
  - `E:\pdet\00_raw` — `.7z` baixados do FTP
  - `E:\pdet\10_parquet` — árvore Parquet final (Hive-particionada)
  - `C:\duckdb_tmp` e `C:\duckdb_tmp\estagio` — **sempre no disco local**,
    nunca no HD externo nem dentro do OneDrive (regra explícita do
    `COMO-RODAR.txt`)
- **Scripts de conferência/reset do ambiente:** `.\pdet-setup.ps1
  -Verificar` e `.\pdet-setup.ps1 -Recriar`.

## 3. Arquitetura do pipeline, por fase

### Fase 0 — Inventário do FTP (`pdet_inventario.py`)
Crawler que mapeia o que existe no servidor **sem baixar microdados**.
Subcomandos: `crawl` (varre e grava `inventario_ftp.csv` + checkpoint
`inventario_state.json`, com `--resume`/`--force`, `--max-depth`,
`--limit`, `--pausa`, `--no-mlsd`) e `report` (gera `relatorio_fase0.md`
a partir do CSV, com fatores `--fator-descompacta`/`--fator-parquet`
calibráveis).

Resultado registrado em `relatorio_fase0.md` (gerado em 2026-08-04):
**3.364 arquivos, 79,5 GB comprimidos**, cobrindo 1985–2026. Distribuição
por base: RAIS_VINCULOS (79 arqs / 33,6 GB), RAIS_OUTRO (947 / 30,9 GB),
NOVO_CAGED_MOV (273 / 8,7 GB), CAGED_ANTIGO (284 / 4,2 GB), RAIS_ESTAB
(12 / 1,3 GB), e bases menores de CAGED/documentação auxiliar. Também tem
quebra por ano, por recorte geográfico (SP sozinho é 19,7 GB comprimidos)
e por extensão (a maioria é `.7z`).

### Fase 1 — Download (`pdet_download.py`)
Motor de download com resume via FTP REST, checkpoint em `manifesto.csv`
(hash SHA-256 por arquivo, idempotente), extração opcional com `py7zr`.
Flags principais: `--dados` (raiz local, obrigatório), `--inventario`,
`--base`/`--ano`/`--recorte` (repetíveis, para filtrar o que baixar),
`--ext` (default `7z`,`zip`), `--extrair`, `--apagar-apos-extrair`,
`--lista` (baixa exatamente os caminhos listados em um `.txt`, apagando
o arquivo local corrompido antes de tentar de novo — usado com
`refazer_download.txt`), `--incluir-parcial`/`--incluir-legado` (as
pastas `Parcial` e `Legado` ficam de fora por padrão), `--dry-run`,
`--sem-hash`.

`manifesto.csv` hoje tem **790 linhas, todas com status `ok`** — ou seja,
todo arquivo que entrou no manifesto foi baixado e validado com sucesso.

Utilitários de apoio criados nesta fase:
- `diagnostico_ftp.py` — distingue bloqueio de firewall corporativo na
  porta 21, instabilidade do servidor do MTE, e bloqueio temporário de IP
  por excesso de requisições (`--insistir N` para retry).
- `plano_rais.py` — lê o `inventario_ftp.csv` local e sugere o comando de
  download certo para um recorte (`--de`/`--ate`/`--uf`, default
  2022–2025 / PI), a partir da estrutura real do FTP (regional vs.
  por-UF).
- Launchers `pdet.ps1` (Windows) e `pdet.sh` (macOS/Linux) com
  subcomandos `inventario`, `relatorio`, `baixar`. O `pdet.ps1` é
  **deliberadamente ASCII puro** (ver seção de aprendizados).

### Fase 2 — Cabeçalhos e conversão para Parquet
- `pdet_cabecalhos.py`: sonda os `.7z` baixados (`--raw`), extrai só o
  cabeçalho (via `py7zr` em streaming ou fallback por subprocesso do
  7-Zip com `--motor auto|py7zr|7z`), confere contra `dic_rais.csv` e
  gera `cabecalhos.csv` + `cabecalhos.md`.
  **Estado atual em `cabecalhos.csv`: 287 arquivos sondados** — 268
  RAIS_VINCULOS, 16 RAIS_ESTAB, 3 RAIS_DOMESTICO. Veredito predominante é
  "OK (nº de colunas) / N rótulo(s) diferentes" (rótulo diferente = nome
  da coluna variou, mas a posição bate); 28 arquivos vieram como
  `DIVERGE` — no bloco de 2010–2012 esses eram na verdade os arquivos de
  `ESTB*.7z`/`Estb*.7z` batendo contra o esquema errado de RAIS_ESTAB
  (2014-2017) por não existir ainda uma janela de esquema cadastrada para
  RAIS_ESTAB 2010-2012 naquele ponto da checagem.
- `dic_rais.csv`: dicionário de colunas por posição, **570 linhas**,
  cobrindo três bases (RAIS_VINCULOS, RAIS_ESTAB, RAIS_DOMESTICO) em
  **8 janelas de esquema observadas**: VINCULOS 2010-2014, 2015, 2016,
  2017, 2018, 2019, 2020-2022, 2023-2025; ESTAB 2010-2012, 2013,
  2014-2022, 2023-2025; DOMESTICO 2015-2017.
- `pdet_parquet.py`: o conversor completo. Lê por **posição de coluna**
  (nunca por nome, por causa das inconsistências entre anos),
  descompacta em streaming, faz staging cross-device (HD externo →
  disco local → HD externo), e escreve Parquet Hive-particionado por
  `ano=`/`uf=`. Flags: `--raw`, `--saida`, `--dic`, `--manifesto`,
  `--tmp`, `--estagio`, `--reserva-gb` (default 20), `--base`/`--ano`/
  `--recorte` (filtros repetíveis), `--paralelo`, `--memoria` (default
  9 GB), `--threads`, `--ate-hora HH:MM` (para parar no fim do
  expediente e retomar no dia seguinte via `conversao.csv`), `--ordem
  menor|maior|ano`, `--refazer`, `--incluir-parcial`/`--incluir-legado`,
  `--dry-run`.
- `pdet_verifica.py`: checador de integridade pós-download/conversão.
  Compara por **caminho FTP completo**, não por nome de arquivo (correção
  de um bug — ver seção 5), e faz **descompactação completa** em vez de
  só checar o CRC do cabeçalho do `.7z` (`py7zr.test()` só confere o
  header). Gera `refazer_download.txt` com a lista de arquivos a rebaixar.

  Estado observado em `conversao.csv` (485 linhas): **287 unidades com
  `status=ok`** (268 RAIS_VINCULOS, 16 RAIS_ESTAB, 3 RAIS_DOMESTICO),
  somando **~4,95 bilhões de linhas** nas unidades OK, cobrindo 2010–2025.
  As linhas com erro nesse arquivo são majoritariamente arquivos de
  `NOVO CAGED\Legado\Estabelecimentos` sendo processados sob o rótulo
  `RAIS_ESTAB` — isso bate com o bug de classificação por caminho descrito
  na seção 5, então é provável que este `conversao.csv` seja uma
  **fotografia de antes da correção** e não o estado mais recente do
  pipeline (ver "Divergências a resolver").

  A memória de longo prazo registra como número mais recente confirmado
  em conversa: **281 de 293 unidades RAIS_VINCULOS convertidas com
  sucesso (~1,26 bilhão de linhas, 2010–2025)**, com **6 arquivos da
  pasta definitiva falhando** (causa ainda sob investigação) — esse é o
  número a considerar como mais atual, vindo diretamente da confirmação
  do Matheus na conversa de 13/08.

### Fase 3 — Banco analítico DuckDB (`pdet_banco.py`)
Construído na conversa de 13/08 (tarde). **Este script, junto com
`consultas.sql` e as tabelas-dimensão `dim_*.csv`, ainda não apareceu no
Project Knowledge** — provavelmente falta subir esses arquivos aqui. Pelo
que ficou definido na conversa:

- `pdet_banco.py` tem cinco subcomandos:
  - `criar` — cria views apontando para o Parquet no HD externo, carrega
    as tabelas-dimensão e ingere os CSVs de proveniência.
  - `checar` — bateria de **11 checagens de integridade** antes de
    agregar; gera `checagem_banco.md`.
  - `codigos` — compara códigos categóricos observados nos dados contra
    o dicionário de rótulos (`dim_codigos.csv`), procurando lacunas.
  - `agregar` — materializa os cubos analíticos em **quatro passadas**
    sobre os dados de vínculos.
  - `consulta` — roda consultas nomeadas de `consultas.sql` com
    substituição de parâmetros.
- Tabelas-dimensão montadas: `dim_municipio.csv` (5.571 municípios do
  IBGE, com hierarquia geográfica incluindo regiões imediatas e
  intermediárias), `dim_cnae_classe.csv` e `dim_cnae_subclasse.csv`
  (CNAE 2.0, via API do IBGE), `dim_codigos.csv` (rótulos de variáveis
  categóricas da RAIS) e `dim_ano.csv` (salário mínimo de dezembro e
  deflator IPCA, indexado a dezembro de 2025 como base).
- `consultas.sql`: **20 consultas nomeadas**, cobrindo séries de estoque
  de emprego, rankings municipais, composição setorial, perfil
  demográfico, fluxos mensais, gap salarial de gênero e checagens de
  validação — lendo Parquet diretamente.
- Todo o pipeline foi testado ponta a ponta contra uma árvore Parquet
  sintética, gerada com os esquemas reais de `dic_rais.csv`, cobrindo três
  períodos de esquema (2013, 2019, 2024) em três UFs. A consistência de
  rollup foi verificada (totais de cubo batendo em todos os níveis de
  agregação).

## 4. Estado atual e pendência imediata

> **Atualizado em 2026-08-31**, depois de uma rodada completa
> (download -> Parquet -> verificação -> banco) feita no Mac sobre um
> recorte parcial: **RAIS_VINCULOS Nordeste 2018-2025 + Piauí 2013-2017 +
> Brasil inteiro 2025** — 19 unidades, 185.068.075 linhas, todas `ok`.
> Detalhes de ambiente estão em `RAIS_MAC.md`; o que segue vale para
> qualquer máquina.

### 4.1 O que a rodada de 31/08 resolveu

**A suspeita de duplicação silenciosa não se confirmou nesse recorte.** As
duas checagens que existem justamente para detectá-la passaram limpas:

- `particao_com_varias_origens` — sem ocorrências. Nenhuma partição
  ano/uf recebeu dados de mais de uma unidade de conversão.
- `conferencia_com_manifesto` — sem ocorrências. A contagem de linhas no
  Parquet bate com a registrada em `conversao.csv`, unidade por unidade.

**Os números reproduzem a rodada anterior dígito por dígito.** Comparando
com o `checagem_banco.md` gerado no Windows em 13/08:

| | Windows (13/08) | Mac (31/08) |
|---|---|---|
| 2025 vínculos declarados (Brasil) | 91.710.262 | 91.710.262 |
| 2025 ativos em 31/12 (Brasil) | 60.691.770 | 60.691.770 |
| Alagoas 2018 / 2022 / 2025 | 651.772 / 797.410 / 1.003.312 | idênticos |
| Acre 2025 | 266.903 | 266.903 |

Duas implementações independentes do mesmo pipeline, em sistemas
operacionais diferentes, chegando ao mesmo número — é a evidência mais
forte disponível de que a leitura por posição de coluna está correta.

### 4.2 O que continua em aberto

**As anomalias de contagem específicas não foram testadas.** O recorte
baixado não cobre AC/AP 2014, MT 2011, RS 2012, SP 2015 nem CE 2016 — os
casos que motivaram a suspeita original. Elas seguem sem veredito: o que
foi demonstrado é que *o mecanismo* de duplicação não está presente onde
houve dados para olhar, não que aqueles anos estejam corretos.

**Próximo passo recomendado (na ordem):**
1. Baixar e converter os anos/UFs das anomalias listadas acima e rodar
   `checar` de novo — é o teste direto que falta.
2. Rodar `codigos` para comparar os códigos categóricos observados contra
   `dim_codigos.csv`.
3. Investigar as 6 unidades RAIS da pasta definitiva que falharam na
   conversão na rodada do Windows.
4. Fazer a conferência cruzada das entradas marcadas `conferir` em
   `dim_codigos.csv` contra os layouts oficiais do MTE antes de qualquer
   publicação — em especial `tipo_vinculo`, `motivo_desligamento`,
   `nacionalidade` e `tipo_admissao` (a coluna `confianca` distingue
   `alta` = já verificado contra o layout oficial, de `conferir` =
   preenchido de memória).
5. Só depois disso, rodar `agregar` para materializar os cubos.

## 5. Aprendizados técnicos e bugs corrigidos

**Esquema da RAIS:**
- Existem pelo menos 7–8 esquemas distintos de vínculos entre 2010–2025
  (mais do que os layouts oficiais do MTE sugerem).
- **Ruptura completa de formato em 2023**: separador mudou de `;` para
  `,`, decimal de `,` para `.`, campos passaram a vir entre aspas, e os
  marcadores de nulo mudaram de `-1`/`{ñ class}` para `999997`/`999999`.
- O layout combinado "2018e2019" publicado pelo MTE está errado: 2018 tem
  62 colunas, 2019 tem 60.
- `Ind Trab Parcial` e `Ind Trab Intermitente` estão **trocadas** a partir
  de 2018.
- **Não existe identificador de estabelecimento** em nenhuma das duas
  bases (vínculos e estabelecimentos), o que torna impossível o join a
  nível de unidade entre elas.
- Por isso, o esquema precisa ser lido **por posição de coluna, nunca por
  nome**.

**Bugs de pipeline encontrados e corrigidos:**
- A função de classificação por caminho (`meta_do_caminho`) comparava o
  **caminho completo do arquivo no `.7z`**, não só o nome do arquivo — o
  que fazia arquivos de vínculos anteriores a 2018 (ex.: `PI2017.7z`)
  serem classificados como `RAIS_ESTAB` porque a pasta-mãe continha a
  palavra "estabelecimento". Da mesma forma, arquivos do CAGED
  (`CAGEDESTAB202001.7z`) batiam no padrão de estabelecimento e eram
  processados com esquema da RAIS. **Isso ainda pode estar presente no
  `conversao.csv` atual do Project Knowledge** — ver seção 6.
- A contagem de linhas por unidade no manifesto estava reportando o total
  acumulado do ano (lido da árvore Parquet final) em vez das linhas da
  própria unidade.
- `pdet_verifica.py` comparava tamanhos de arquivo por **nome**, entre
  todos os caminhos do FTP (produzindo valores de "truncamento" negativos
  e impossíveis), e usava `py7zr.test()`, que só confere o CRC do
  cabeçalho, não a descompactação real.
- `ftplib.nlst()` muda silenciosamente a sessão FTP para modo ASCII,
  quebrando comandos `SIZE` subsequentes — corrigido reemitindo `TYPE I`
  antes de cada consulta de tamanho.
- `ConnectionRefusedError` na conexão inicial provavelmente indica
  proteção antiflood do servidor do MTE, não bloqueio permanente — vale
  reconectar com espera.
- PowerShell 5.1 lê `.ps1` sem BOM como cp1252, então os bytes UTF-8 de
  travessão (`—`, `E2 80 94`) viram aspas curvas e quebram o parser. Todo
  `.ps1` do projeto é ASCII puro com quebra de linha CRLF.

### Achados de 2026-08-31 (rodada no Mac, recorte Nordeste + PI + 2025)

**Os zeros de remuneração viraram nulos em 2023.** Este é o achado mais
consequente da rodada, e não estava mapeado. Até 2022, `remun_dez_nom` traz
`0` literal para quem não recebeu em dezembro. **A partir de 2023 não existe
mais nenhum zero** — todos viraram `NULL` (via os marcadores `999997`/
`999999` da ruptura de 2023):

| ano | linhas | zeros | nulos |
|---|---|---|---|
| 2021 | 12.190.056 | 3.399.724 | 0 |
| 2022 | 13.584.961 | 4.178.619 | 0 |
| 2023 | 14.577.485 | **0** | **5.190.036** |
| 2024 | 15.465.156 | 0 | 5.726.289 |
| 2025 | 16.641.624 | 0 | 6.387.628 |

*(Nordeste; o padrão é estrutural, não regional.)*

Isso **quebra silenciosamente qualquer série de remuneração que cruze
2022/2023**, porque a população do denominador muda sem aviso. Medido entre
os vínculos ativos em 31/12 do Nordeste:

| série | 2022 | 2023 | variação |
|---|---|---|---|
| mediana, sem tratamento | 1.696,80 | 1.928,48 | **+13,7%** |
| mediana, excluindo zeros dos dois lados | 1.800,00 | 1.928,48 | **+7,1%** |
| média, sem tratamento | 2.779,66 | 3.284,85 | +18,2% |
| média, excluindo zeros dos dois lados | 3.022,86 | 3.284,85 | +8,7% |

O crescimento aparente é praticamente o **dobro** do real. A regra é sempre
filtrar `remun_dez_nom > 0` (ou tratar `0` e `NULL` como a mesma coisa) em
qualquer agregado que atravesse 2023 — vale para média, mediana, quantis e
qualquer contagem do tipo `WHERE remun = 0`, que retorna zero a partir de
2023 sem erro nenhum.

**A faixa de referência da checagem 10 é do Nordeste, não do Brasil.** A
checagem `coerencia_com_salario_minimo` diz esperar mediana entre 1,3 e 1,6
salários mínimos. Isso vale para o Nordeste (1,40-1,47 em todos os anos de
2013 a 2025), mas **não para o Brasil**: em 2025, o país inteiro dá **1,81**
e só o Nordeste dá 1,43, com o mesmo dado e o mesmo código. A faixa
documentada dispararia falso alarme numa rodada nacional. Ao ler essa
checagem, conferir antes qual é o recorte carregado.

**`salario_contratual` e `tipo_salario` só existem em 2018.** Aparecem numa
única janela de esquema. Não dá para montar série com elas.

**Os arquivos de vínculos só são regionais a partir de 2018.** No FTP,
`RAIS_VINC_PUB_<REGIAO>.7z` (CENTRO_OESTE, MG_ES_RJ, NORDESTE, NORTE, SP,
SUL, + `_NI`) existe de 2018 a 2025. De 1985 a 2017 é **um `.7z` por UF**
(`PI2017.7z`, `BA2013.7z`). A regra `RAIS[_ ]?VINC` do `pdet_inventario.py`
não casa com esses nomes, então eles são rotulados **`RAIS_OUTRO`** no
inventário, com `recorte` = sigla da UF.

Consequência prática: `--base RAIS_VINCULOS --recorte NORDESTE --ano 2017`
seleciona **zero arquivos e não dá erro** — parece "download concluído". Para
o Nordeste pré-2018 é preciso `--base RAIS_OUTRO` com `--recorte` repetido
para MA, PI, CE, RN, PB, PE, AL, SE, BA. O `pdet_parquet.py` classifica
certo (tem a regra `^<UF>\d{4}` em `meta_do_caminho`); é só o inventário que
diverge. **Sempre conferir com `--dry-run` antes de um backfill longo.**

### Armadilhas de operação dos scripts (não são bugs de dado)

- **`pdet_banco.py criar --dicionarios` aponta para `dicionarios/` por
  padrão, mas os `dim_*.csv` moram na raiz do repositório.** Sem
  `--dicionarios .`, cinco das doze checagens falham com "Table with name
  dim_municipio does not exist" — foi exatamente o que aconteceu no
  `checagem_banco.md` de 13/08. Não é problema de dado.
- **`--meta` quer uma pasta só, mas os CSVs de proveniência estão em dois
  lugares**: `dic_rais.csv`, `inventario_ftp.csv` e `cabecalhos.csv` no
  repositório; `conversao.csv` e `manifesto.csv` em `<dados>/03_meta`.
  Montar uma pasta com links para os cinco resolve.
- **`pdet_verifica.py --manifesto` só aceita `conversao.csv`**, que tem a
  coluna `arquivo`. Passar o `manifesto.csv` do download (coluna
  `arquivo_local`) dá `KeyError`.
- **`refazer_download.txt` só é reescrito quando há algo a refazer.** Uma
  verificação limpa deixa o arquivo antigo intacto, então um
  `refazer_download.txt` presente **não** significa que há pendências —
  conferir a data.

**Ambiente FTP do MTE:** o servidor tem instabilidade documentada e
proteção antiflood — crawling agressivo pode gerar bloqueio temporário de
IP.

## 6. Divergências a resolver

- **`pdet_banco.py`, `consultas.sql` e os `dim_*.csv`** foram construídos
  e testados na conversa de 13/08 (tarde), mas não estão entre os
  arquivos hoje disponíveis no Project Knowledge. Vale subi-los para que
  fiquem disponíveis nas próximas sessões.
- **`conversao.csv` do Project Knowledge parece ser uma fotografia
  anterior à correção do bug de classificação por caminho**: ele mostra
  198 linhas de erro rotuladas `RAIS_ESTAB` que, pelos nomes dos
  arquivos, são na verdade unidades de `NOVO CAGED\Legado\Estabelecimentos`
  sendo processadas com o esquema errado — exatamente o bug descrito na
  seção 5. O número mais confiável de unidades RAIS convertidas com
  sucesso é o que ficou confirmado em conversa (**281 de 293**), não a
  contagem bruta desse CSV (287 "ok", sem os 6 que a conversa registra
  como falha da pasta definitiva). Ao retomar o trabalho, vale confirmar
  com Matheus se o `conversao.csv` local já está mais novo do que este.
- **Gerenciador de ambiente**: a memória registrava "Anaconda/conda" como
  gerenciador principal; os arquivos do projeto (`pyproject.toml`,
  `uv.lock`, `COMO-RODAR.txt`) mostram que o fluxo principal hoje é `uv`,
  com suporte a conda como intérprete alternativo nos launchers. Ajustei
  esse ponto neste documento.

## 7. Histórico de conversas (para referência)

1. **04/08/2026 — "Gerenciamento de microdados RAIS e Caged em
   infraestrutura local"**: Fase 0 (inventário) e Fase 1 (download) —
   `pdet_inventario.py`, `pdet_download.py`, launchers, `diagnostico_ftp.py`,
   `plano_rais.py`, `baixa_rais_nordeste.py` (downloader avulso para um
   arquivo específico, criado depois que o cliente FTP do Windows Explorer
   deu timeout em arquivos grandes).
2. **13/08/2026, manhã — "Otimizando banco de dados RAIS para relatórios
   anuais"**: Fase 2 — análise dos layouts oficiais do MTE, construção do
   dicionário de colunas, `pdet_cabecalhos.py`, `pdet_parquet.py`,
   `pdet_verifica.py`, `pdet-setup.ps1`, correção dos bugs de
   classificação e verificação.
3. **13/08/2026, tarde — "Preparação do banco de dados SQL"**: Fase 3 —
   `pdet_banco.py`, tabelas-dimensão, `consultas.sql`, teste ponta a ponta
   com dados sintéticos, identificação da anomalia de contagem de linhas
   em `conversao.csv`.
