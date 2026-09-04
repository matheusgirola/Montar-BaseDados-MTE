# CLAUDE.md — Pipeline de microdados RAIS/PDET (SEPLAN-PI)

> **Este é o arquivo canônico do projeto.** Toda lição, bug corrigido e
> achado sobre os dados mora aqui — é o primeiro lugar a consultar antes de
> qualquer atualização futura do pipeline, e o único que se pretende
> permanente. Os outros dois documentos do repositório têm papéis
> diferentes e não duplicam este conteúdo, só apontam para ele:
>
> - `RETOMAR.md` é o estado da sessão mais recente — "onde paramos, o que
>   fazer a seguir". É descartável: reescreva-o a cada retomada em vez de
>   acumular histórico nele.
> - `docs/COMO-RODAR-BANCO.txt` é o runbook operacional da fase 3 (o banco
>   DuckDB) — só comandos e caminhos, sem narrativa de como cada lição foi
>   descoberta.
>
> A estrutura de pastas do repositório está descrita na seção 8.

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

> **Atualizado em 2026-09-02**, depois de uma rodada sobre a **base
> nacional completa** na máquina Windows: `E:\pdet\10_parquet` cobre
> **RAIS_VINCULOS e RAIS_ESTAB, 2010-2025, todas as UFs** — 875 arquivos,
> 44,7 GB, **1.178.045.148 linhas** de vínculos. As rodadas anteriores
> (13/08 no Windows, 31/08 no Mac, esta última descrita em `RAIS_MAC.md`)
> trabalhavam sobre recortes; esta é a primeira sobre o país inteiro.

### 4.1 A conversão da RAIS está completa

O manifesto tem **284 arquivos RAIS da pasta definitiva** e o
`E:\pdet\03_meta\conversao.csv` tem **284 unidades, todas `ok`**. Não há
unidade RAIS pendente nem com erro.

**As "6 unidades RAIS da pasta definitiva que falharam", registradas em
versões anteriores deste documento, não existem.** Os 6 `LZMAError` do
`conversao.csv` antigo são arquivos de `NOVO CAGED\Legado\Estabelecimentos`
rotulados `RAIS_ESTAB` pelo bug de classificação por caminho (seção 5) —
não são RAIS, não são da pasta definitiva, e a falha não é do pipeline: os
arquivos estão corrompidos na origem (ver 4.3).

O `conversao.csv` da raiz do repositório continua sendo a fotografia
pré-correção, com 485 linhas e 198 erros. **O bom é o de
`E:\pdet\03_meta`.** Ao montar a pasta de `--meta`, pegue o de lá.

### 4.2 As duas suspeitas antigas morreram, com a base inteira na mão

**Não há duplicação em lugar nenhum.** As três checagens que existem para
detectá-la passaram limpas sobre os 44,7 GB: `particao_com_varias_origens`
sem ocorrências, `conferencia_com_manifesto` sem ocorrências (linha a
linha, 284 unidades) e `uf_incoerente` sem ocorrências. E `estoque_brasil`
reproduz a RAIS publicada ano a ano — 2010: 44.068.355; 2014: 49.571.510;
2019: 46.716.492.

**As "quedas verticais" de MT 2011, RS 2012, SP 2015 e CE 2016 não
existem.** Com a série completa: MT 2011 = **+11,2%** (subida), RS 2012 =
**+3,5%**, SP 2015 = **−6,0%**, CE 2016 = **−6,8%**. A queda de 2015-2016
aparece em **todas as 27 UFs ao mesmo tempo** (SP −6,0/−7,2, RS −6,8/−6,7,
MT −3,6/−7,5, CE −1,8/−6,8, AC −0,3/−8,0). Isso é a recessão, não
truncamento: truncamento de arquivo não acontece em 27 estados no mesmo par
de anos.

**A anomalia "AC e AP idênticos em 2014" nunca existiu** — AC 191.604 vs
AP 184.811. A checagem `anomalia_ano_uf` não encontra nenhuma contagem
idêntica entre UFs em nenhum ano.

**Sobra um único caso, e ele se explica.** RR 2023, +30,8%. Roraima tem 15
municípios na base em todos os anos (duplicação de arquivo mudaria isso), e
os estabelecimentos do estado saltaram **+69,2%** em 2023 contra +39% no
Brasil, com RAIS negativa +156%. É a expansão de cobertura do eSocial, que
pegou Roraima mais forte que qualquer outro estado. Parte do salto também é
efeito de vintage — ver 4.3.

### 4.3 As pastas `Legado`: o achado desta rodada

`Legado` **não é outra medição do mesmo ano. São duas coisas ao mesmo
tempo**, e as duas importam.

**(a) É o mesmo ano em outro layout.** O `RAIS/2023/Legado` traz o dado de
2023 no **layout de 2019**: 60 colunas, separador `;`, decimal `,`, campos
preenchidos com zeros à esquerda, nulos `9997`, arquivo interno `.txt`. A
definitiva de 2023 traz 62 colunas, separador `,`, decimal `.`, aspas,
nulos `999997`/`999999`, arquivo interno **`.COMT`**. O cabeçalho do Legado
2023 é idêntico ao da definitiva de 2019 — a única diferença nos 60 nomes é
o sufixo das colunas de remuneração mensal (`SC` no Legado, `CC` em 2019),
na mesma posição.

E a ordem das colunas difere de verdade entre os dois layouts: nas posições
13 a 16 o Legado traz `Faixa Etária, Faixa Hora Contrat, Faixa Remun Dezem
(SM), Faixa Remun Média (SM)` e a definitiva traz `Faixa Etária, Faixa Rem
Média (SM), Faixa Hora Contrat, Faixa Rem Dez (SM)`. **Ler por nome aqui
daria número errado sem erro nenhum.** É a justificativa mais concreta que
já apareceu para a regra de ler por posição.

Para converter, use a flag nova **`--esquema-ano`** do `pdet_parquet.py`:
lê com o esquema do ano indicado, mas particiona no ano real do dado.

```
python pdet_parquet.py --raw "E:\pdet\00_raw\...\RAIS\2023\Legado"
    --saida E:\pdet\10_parquet_legado
    --manifesto E:\pdet\03_meta\conversao_legado.csv
    --incluir-legado --esquema-ano 2019
```

Sem ela o conversor escolhe o esquema pelo ano do caminho e morre com
`Expected 62 columns, got 17`.

**(b) É outra vintage do dado, e a diferença é grande.** Convertido o
Legado 2023 inteiro (8 unidades, 81.537.467 linhas), os vínculos ativos em
31/12 dão **54.706.385** — exatamente o número da publicação oficial do
MTE. A definitiva servida hoje pelo FTP dá **55.818.007**, uma diferença de
**1.111.622 (+2,03%)**.

**A revisão é quase inteiramente administração pública.** Por grupo de
natureza jurídica, Brasil 2023, vínculos declarados:

| grupo | Legado | definitiva | diferença |
|---|---|---|---|
| 1 — administração pública | 12.725.788 | 14.207.327 | **+1.481.539** |
| 2 — entidades empresariais | 60.675.521 | 60.626.835 | −48.686 |
| 3, 4 e 5 | 5.468.198 | 5.464.446 | −3.752 |
| 9 ↔ nulo | 2.667.960 | 2.667.914 | artefato do marcador de nulo |

E ela é **muito concentrada por UF**. Ativos em 31/12, definitiva contra
Legado: **DF +28,4%** (+341.135, sozinho 31% da diferença nacional),
RR +14,8%, PB +11,2%, RO +8,8%, RJ +5,8%, MG +3,1% — enquanto TO −3,7%,
MT −1,9%, PR −0,4% e PE −0,04% vão para baixo. No DF, os +425.973 vínculos
declarados a mais são **+422.414 de administração pública** — ou seja,
declarações do governo federal que faltavam na versão usada na publicação.

**Consequência prática, e é séria:** um relatório que cite "RAIS 2023 =
54,7 milhões" (o número oficial) **não vai bater** com a base montada a
partir da pasta definitiva, que dá 55,8 milhões. Toda comparação com
número publicado pelo MTE precisa dizer **qual vintage** foi usada. Para o
DF a diferença é de 28% — não é detalhe de arredondamento.

**Para 2019 não dá para fazer o mesmo teste: os arquivos estão corrompidos
no servidor do MTE.** Dos 6 `.7z` de `RAIS/2019/Legado`, **5 quebram na
descompactação** — SP em 5% do arquivo, SUL em 6%, NORDESTE em 38%,
MG_ES_RJ em 73%, NORTE em 76%. Não é truncamento (o tamanho bate ao byte
com o FTP) nem problema de transferência: rebaixar produz **MD5 idêntico**.
Só o CENTRO_OESTE está íntegro, e nele a comparação é reveladora — os dois
vintages têm **exatamente as mesmas 6.086.200 linhas**, mas **4.085.381
ativos na definitiva contra 4.141.894 no Legado**: a revisão de 2019 não
acrescentou vínculo nenhum, **reclassificou 56.513 como não-ativos em
31/12**.

Em `E:\pdet\10_parquet_legado`, portanto, **`ano=2019` é só o Centro-Oeste
(GO/MT/MS/DF)**. Não some isso como se fosse o ano inteiro.

### 4.4 O que continua em aberto

1. **40 combinações variável/código sem rótulo** (eram 139), quase todas
   posteriores a 2022 — o MTE não publicou layout de 2023 em diante. A
   maior é `categoria_trabalhador` (22 códigos, 262 milhões de linhas,
   2023-2025), a tabela de categorias do eSocial. Ver seção 5.
2. Se a pasta `Legado` de 2019 for mesmo necessária, o caminho é **pedir os
   arquivos ao MTE** — insistir no FTP não resolve.

> **Os cubos ficaram prontos em 03/09** (ver 4.7). Os sete cubos cobrem
> 2010-2025, o rollup fecha em zero nos quatro grãos, e os totais reproduzem
> a RAIS publicada ano a ano. Com isso a fase 3 está inteira: `criar`,
> `checar`, `codigos`, `agregar` e `consulta` todos rodados sobre a base
> nacional.

> A pendência de reconverter os vínculos de 2023-2025 **foi fechada em
> 03/09**: as 21 unidades foram reconvertidas com a lista de nulos corrigida,
> e o manifesto tem 284 unidades todas `ok`. Conferido no dado: o `99` voltou
> a ser valor em `idade` (76 casos em 2023, 96 em 2024, 110 em 2025) e em
> `qtd_dias_afastamento` (8.965, 6.404, 4.059), sem nulo sobrando; as
> sentinelas de verdade continuam nulas; e a contagem de ativos não mudou em
> ano nenhum. Dicionário e árvore voltaram a descrever a mesma coisa.

### 4.5 A divergência dos estabelecimentos pós-2023, resolvida

A soma de `qtd_vinculos_ativos` declarada pelos estabelecimentos não fechava
com a contagem de vínculos ativos a partir de 2023 — 2023: −570.144; 2024:
−738.659; 2025: −799.368 — e fechava na unidade de 2010 a 2022. **Eram duas
causas somadas, e as duas foram fechadas.**

**(a) Um bug nosso, de 68.751 vínculos em 2023.** A lista de marcadores de
ausente era **uma por esquema e ia aplicada a todas as colunas**. Para
2023-2025 essa lista é `999997|999999|999|99|9997|9999` — então um
estabelecimento com exatamente **99 vínculos ativos virava NULL**. Lido
direto do `.7z` cru de 2023, sem passar pelo conversor:

| | |
|---|---|
| soma escrita pelo MTE | **55.316.614** |
| soma que o banco tinha | 55.247.863 |
| comido pela lista | **68.751** |
| valores anulados | `99` × 644, `999` × 5 |

644 × 99 + 5 × 999 = 68.751, ao vínculo. O mesmo em 2024 (−70.164) e 2025
(−78.543).

O `dic_rais.csv` **sempre teve a coluna `nulos` por linha** — o conversor é
que colapsava tudo na primeira. Corrigido: `Esquema.nulos_col` guarda a lista
por coluna e `montar_select` passa a de cada uma. No dicionário, as cinco
colunas onde o all-9s curto é **grandeza e não sentinela** (`qtd_vinculos_clt`,
`qtd_vinculos_ativos`, `qtd_vinculos_estat`, `idade`,
`qtd_dias_afastamento`) ficaram só com `999997|999999`.

**Onde o marcador curto é sentinela de verdade, ele continua valendo** —
`qtd_hora_contr` = 99 (o máximo legal é 44), `mun_trab` = 999999,
`cbo_2002` = 999999, `causa_afastamento_*` = 999, os bairros = 999997.

**(b) O resto não é bug: são os vínculos abandonados.** Sobravam 501.393 em
2023 e eles têm nome — `ind_vinculo_abandonado = 1`, coluna que só existe de
2023 em diante. O estabelecimento não os declara como ativos; a base de
vínculos os marca ativos. Reconvertidos os estabelecimentos, a conta fecha
**exatamente em zero** nos três anos:

| ano | ativos (vínculos) | declarado (estab.) | diferença | abandonados | sobra |
|---|---|---|---|---|---|
| 2022 | 52.790.864 | 52.790.864 | 0 | 0 | **0** |
| 2023 | 55.818.007 | 55.316.614 | −501.393 | 501.393 | **0** |
| 2024 | 57.800.651 | 57.132.156 | −668.495 | 668.495 | **0** |
| 2025 | 60.691.770 | 59.970.945 | −720.825 | 720.825 | **0** |

**Consequência para relatório:** "estoque de emprego formal" pela base de
vínculos e pela base de estabelecimentos são números legitimamente
diferentes de 2023 em diante, e a diferença é o vínculo abandonado. Diga
qual das duas foi usada.

A checagem nova **`conciliacao_estab_vinculos`** faz exatamente essa conta e
exige `sobra = 0`. Ela existe porque a 5 mostrava a contagem e a 13 mostrava
a soma declarada, mas **ninguém subtraía uma da outra** — e a diferença
passou meses despercebida.


### 4.6 O HD externo derruba rodada longa — e isso mudou o procedimento

Em 03/09 o disco caiu **duas vezes**. Na primeira sumiu por cinco segundos e
voltou sozinho, matando a gravação do `conversao.csv` com
`OSError: [Errno 22]`. Na segunda **sumiu de vez**, no meio da 18ª de 21
unidades: o `Win32_DiskDrive` deixou de enxergar o dispositivo e só voltou
com reinício do PC. Não é o Windows soltando a letra da unidade — é o
dispositivo caindo.

O padrão dos dois episódios é o mesmo: **leitura sequencial pesada e contínua
por muitos minutos.** As duas rodadas usavam `--threads 8 --memoria 8` e
emendavam dezenas de unidades sem parar.

**O procedimento para qualquer rodada longa no HD externo passou a ser:**

- `--threads 2 --memoria 3`, não 8 e 8
- prioridade do processo abaixo do normal
- **uma unidade (ou um ano) por invocação**, para que o manifesto seja
  gravado ao fim de cada uma e uma queda perca no máximo a unidade em curso
- pausa de 60 a 90 segundos entre unidades

Refeito assim, o mesmo trabalho que havia derrubado o disco terminou sem um
único evento no vigia. Os dois scripts prontos são
`C:\pdet\resume_vinc.ps1` (conversão) e `C:\pdet\agregar_lento.ps1`
(cubos, ano a ano).

**Duas armadilhas de operação que custaram tempo:**

- **O reinício mata o vigia**, e o `powercfg` volta ao padrão a cada logon.
  Os dois precisam ser refeitos **e conferidos** depois de todo boot.
- **O comando que confere se o vigia está de pé contava o próprio processo
  que o executava**, porque a linha de comando dele contém a palavra
  procurada — respondia "1 vigia rodando" com zero vigias. Exclua o `$PID`:

  ```powershell
  $meu = $PID
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
      Where-Object { $_.ProcessId -ne $meu -and $_.CommandLine -like '*watchdog.ps1*' }
  ```

Se a queda repetir mesmo com o consumo reduzido, o próximo lugar para olhar é
a política de energia **do próprio dispositivo** (Gerenciador de
Dispositivos, aba Gerenciamento de Energia do controlador USB) e a
alimentação do gabinete do HD.


### 4.7 Os cubos, materializados — e o que a rodada ensinou

Rodados em 03/09 pelo `C:\pdet\agregar_lento.ps1`, **um ano por
invocação**. Resultado: sete cubos, 2010-2025, **48 min** de ponta a ponta
(incluindo as pausas e uma falha no meio).

| cubo | linhas |
|---|---|
| `fato_estab_mun` | 4.373.869 |
| `fato_vinc_mun_secao` | 1.228.010 |
| `fato_vinc_fluxo_mes` | 1.055.771 |
| `fato_vinc_perfil` | 812.945 |
| `fato_vinc_ocupacao` | 338.648 |
| `fato_vinc_mun` | 89.113 |
| `fato_vinc_tamanho` | 4.351 |

**O rollup fecha exatamente em zero** entre os quatro grãos (município,
seção, tamanho, perfil) em todos os 16 anos, e os `ativos` reproduzem a RAIS
publicada — 2010: 44.068.355; 2014: 49.571.510; 2019: 46.716.492; 2025:
60.691.770.

**A correção dos denominadores valeu o que se esperava dela.** Medido no
Parquet, com as duas fórmulas lado a lado:

| ano | ativos | nulos de remun. | zeros | fórmula antiga | fórmula nova |
|---|---|---|---|---|---|
| 2022 | 52.790.864 | **0** | 4.463.969 | 3.437,30 | 3.754,80 |
| 2023 | 55.818.007 | **6.744.178** | **0** | 4.043,47 | 4.043,47 |

A troca de zeros por nulos é **total** e acontece de um ano para o outro,
então a fórmula antiga muda de denominador sozinha na virada: daria
**+17,6%** de 2022 para 2023, onde o crescimento real é **+7,7%**. É a
mesma proporção medida no Nordeste em 31/08 (+13,7% contra +7,1%), agora
confirmada no país inteiro. Com a correção a série fica lisa: 7,6% → 7,7%
→ 6,1% → 3,4%.

Repare que **`massa_dez` atravessa 2023 sem distorção em qualquer
denominador** — `sum()` ignora `NULL` e soma zero. Um teste montado sobre
`massa_dez / ativos` **não detecta o bug**; só o `avg()` o expõe.

**A partir de 2023 o cubo municipal estoura 4 GB.** O `GROUPING SETS` de
município × seção × tamanho chega a ~1,2 milhão de grupos, e cada grupo
carrega o estado do `approx_quantile` — que o DuckDB **não derrama para
disco**. 2022 passou raspando; 2023 morreu com
`OutOfMemoryException: Allocation failure` depois de 7,8 min.

O contraintuitivo é que **subir a memória deixou mais rápido, não mais
lento**: com `--memoria 6 --threads 2` os anos de 2023 a 2025 levaram 1,2-1,3
min cada, contra 2,3 min de 2022 com `--memoria 4 --threads 4`. A lentidão
não vinha das threads, vinha do derrame. O `agregar_lento.ps1` já escolhe
6 GB / 2 threads de 2023 em diante.

**E isso não conflita com a regra do HD** (4.6): o que derruba o disco
externo é leitura sequencial contínua, não teto de RAM. Mais memória
significa **menos** derrame para `C:\pdet\tmp`, não mais I/O no `E:`.

Se um dia 6 GB não bastar, o caminho não é mais memória: é tirar o
`approx_quantile` do cubo de grão fino e calcular a mediana numa passada
separada, porque é só ele que não derrama.

### 4.8 AC 2021: dezembro incha na administração pública (é da fonte)

Achado ao rodar `hiato_sexo` sobre os cubos prontos. **AC 2021 é a única
combinação UF×ano em 432 com hiato de gênero acima de +10%** — mulheres com
5.568,86 contra 4.316,52 dos homens, num painel que é negativo em
praticamente todo o resto. A massa feminina do AC vai de 179,2 mi (2020) para
351,8 mi (2021) e volta para 230,6 mi (2022).

**Não são outliers.** O topo 1% contribui *menos* em 2021 (4,7% da massa
feminina contra 8,3% em 2020) e o máximo é *menor*. O que se move é o miolo
alto: o p90 dobra e volta.

**Não é bug nosso.** Duas evidências independentes:

| | 2020 | 2021 | 2022 |
|---|---|---|---|
| p90 da remuneração **de dezembro** | 6.943 | **14.582** | 6.860 |
| p90 da remuneração **média do ano** | 6.713 | **6.720** | 6.914 |

Primeiro, 2020-2022 caem na mesma janela de esquema e passam pelo mesmo
código, pelas mesmas posições de coluna — e os dois anos vizinhos estão
corretos. Segundo, a remuneração média do ano, lida **da mesma linha do mesmo
arquivo**, está intacta. Erro de leitura ou de decimal não escolhe uma coluna
e poupa a vizinha.

**Está inteiro na administração pública.** Média de dezembro por grupo de
natureza jurídica:

| grupo | 2020 | 2021 | 2022 | n (2021) |
|---|---|---|---|---|
| 1 — administração pública | 4.855 | **8.232** | 5.206 | 61.299 |
| 2 — entidades empresariais | 1.955 | 2.044 | 2.163 | 63.290 |
| 3, 4 e 5 | estáveis | estáveis | estáveis | — |

É algo pago em dezembro de 2021 pelo setor público acreano — retroativo,
precatório ou reajuste — que o campo de dezembro capta e o de média anual
dilui.

**Consequência para relatório:** qualquer recorte de **remuneração de
dezembro** que inclua AC 2021 vai destoar, e o hiato de gênero inverte de
sinal. Para série de remuneração do Acre que atravesse 2021, prefira
`remun_media_nom`, que não tem o efeito. E vale a suspeita geral: **um pico
isolado de remuneração de dezembro na administração pública provavelmente é
pagamento extraordinário, não mudança salarial** — conferir sempre contra a
média do ano antes de escrever qualquer coisa a respeito.

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
- **A lista de marcadores de ausente era uma por esquema, aplicada a todas
  as colunas.** Em 2023-2025 essa lista tem `99` e `999`, que são sentinela
  num campo de duas casas e **grandeza** noutro: um estabelecimento com 99
  vínculos ativos virava NULL. Custou 68.751 vínculos só em 2023. O
  `dic_rais.csv` já trazia `nulos` por linha; o conversor é que colapsava na
  primeira. Ver 4.5. **A lição geral: marcador de ausente é propriedade da
  coluna, não do arquivo** — e o all-9s curto só é ausente quando preenche a
  largura do campo.

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

**Em 03/09 os cubos passaram a carregar as duas populações.** O `agregar`
calculava `remun_dez_media` com `avg(remun_dez_nom) FILTER (WHERE
vinculo_ativo_3112)` e a mediana com o mesmo filtro — ou seja, herdava a
ruptura inteira: até 2022 o denominador incluía os zeros, de 2023 em diante
não. Teria produzido, depois de horas de varredura, um cubo com salto
artificial em 2023 na média e na mediana de **todos** os recortes. Agora
cada cubo grava `ativos` (todos) e `ativos_com_remun` (os que receberam), a
média e a mediana saem sobre a segunda, e as views `v_*` dividem `massa_dez`
por `ativos_com_remun`.

`massa_dez` nunca precisou de tratamento — `sum()` ignora `NULL` e soma
zero, então a massa salarial atravessa 2023 sem distorção. É só a média e a
mediana que quebram.

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

### Achados de 2026-09-02 (rodada nacional no Windows)

Todos vieram de conferir o `dim_codigos.csv` contra os **layouts oficiais
do MTE**, que agora estão baixados em
`E:\pdet\00_raw\pdet\microdados\RAIS\Layouts\`. Antes disso, 52 rótulos
estavam marcados `conferir` (preenchidos de memória). Hoje o arquivo tem
**311 linhas, 309 delas `alta`**, cada uma com a fonte na coluna
`observacao`.

**A faixa de remuneração de dezembro estava deslocada em uma posição
inteira.** Este é o erro mais grave encontrado até hoje no projeto.

O layout (aba `FAIXAS`) diz que `FAIXA REMUNERAÇÃO MÉDIA DE DEZEMBRO`
começa em **`00 = Não Ativ Dez`** e só depois vêm as faixas: `01` = até
0,50 SM, `02` = 0,51 a 1,00, e assim até `12` = mais de 20,00. O
`dim_codigos.csv` rotulava `0` como "Até 0,50 SM" e seguia deslocado até o
fim, sem o código `12`.

Conferido direto no dado, em 2019 (salário mínimo R$ 998,00):

| faixa | linhas | % ativos em 31/12 | remuneração mín-máx |
|---|---|---|---|
| 0 | 19.113.206 | **0,02%** | 0,00 (mediana 0,00) |
| 1 | 331.959 | 99,75% | 299,40 a 508,97 (**até 0,51 SM**) |
| 2 | 2.536.222 | 99,80% | 508,98 a 1.007,97 (**0,51 a 1,01 SM**) |
| 3 | 11.659.743 | 99,72% | 1.007,98 a 1.506,97 |
| 12 | 514.038 | 99,67% | a partir de 19.969,98 (**20,01 SM**) |

Cada limite cai no múltiplo exato do salário mínimo — com a escala
deslocada, e só com ela. A faixa `0` tem 0,02% de ativos e mediana de
remuneração zero: é "não ativo em dezembro", não "até meio salário".

**O tamanho do estrago:** `faixa_remun_dez_sm = 0` tem **295.922.633
linhas** e estava rotulada "Até 0,50 SM". Qualquer distribuição salarial
montada sobre essa variável jogaria 296 milhões de vínculos **sem emprego
em dezembro** na faixa salarial mais baixa, e deslocaria todas as outras
faixas em uma posição.

**E a escala da remuneração MÉDIA mudou em 2023.** Até 2022 ela vai de
`00` (até 0,50 SM) a `11` (mais de 20,00). **A partir de 2023 passou a ir
de `01` a `12`**, igual à de dezembro. Conferido em 2023 (SM R$ 1.320,00):
o teto da faixa 1 é 660,00 (0,50 SM), o da faixa 2 é 1.320,00 (1,00 SM), o
da 3 é 1.980,00 (1,50 SM), e assim por diante — todos múltiplos exatos.

Ou seja: **o mesmo código quer dizer faixas diferentes dos dois lados de
2023.** O código `2` vale "1,01 a 1,50 SM" até 2022 e "0,51 a 1,00 SM" de
2023 em diante. Por isso o `dim_codigos.csv` ganhou as colunas
**`ano_de`/`ano_ate`**, e o `codigos` do `pdet_banco.py` passou a casar o
rótulo pela janela de anos, não só por variável e código.

**`tipo_admissao` estava deslocado.** O dicionário trazia `5` =
Reintegração e `6` = Recondução/reversão. O layout diz que **`5` não
existe**, `6` = Reintegração, `7` = Recondução, `8` = Reversão, `9` =
Requisição, e `10` a `14` são movimentações de servidor público. Todo
vínculo com `tipo_admissao = 6` (435.995 linhas) estava sendo contado como
"recondução/reversão" quando é **reintegração**, e os códigos 7 a 14 não
tinham rótulo nenhum. (O código `5` aparece de fato no dado, mas só de 2022
em diante e em 988 linhas — ficou sem rótulo de propósito, porque nenhum
layout o documenta.)

**`tipo_vinculo` 96 e 97 tinham o mesmo rótulo.** O 97 estava como
"Contrato prazo indeterminado — lei estadual". O layout diz `96 = CONT LEI
EST` e `97 = CONT LEI MUN`: o par é estadual/municipal.

**Lacunas grandes que foram preenchidas:** `motivo_desligamento` tinha 6 de
30 códigos — faltavam todos os desligamentos do setor público, os quatro de
falecimento, os onze de aposentadoria e o **90, "desligamento por acordo"**,
criado pela reforma trabalhista de 2017. `nacionalidade` tinha 2 de 47 —
qualquer corte de trabalhador estrangeiro sairia quase todo sem rótulo, e o
código 26 (venezuelana) é justamente o que interessa no caso de Roraima.

**O layout de 2020 é MENOS completo que o de 2017.** As causas de
afastamento (`10` acidente típico, `20` acidente de trajeto, `30` doença
relacionada ao trabalho, `40` doença não relacionada, `50`
licença-maternidade, `60` serviço militar, `70` licença sem vencimento)
estão no layout de 2017 e **sumiram do de 2020**, que só lista `99 = sem
afastamentos`. Vale guardar todos os layouts, não só o mais novo.

**Os marcadores de "ignorado" no arquivo não são os do layout.** A nota do
próprio layout manda tratar `-1`, `{ñ class}` e `{ñclass}` como ignorado —
mas nos arquivos esse marcador vem escrito **`99`** em `raca_cor` (130
milhões de linhas, 2010-2022), `faixa_etaria`, `faixa_hora_contrat`,
`faixa_tempo_emprego` e `ibge_subsetor`. A aba `FAIXAS` confirma, mapeando
`99 → {ñ class}` na faixa de dezembro.

**O que sobrou sem rótulo, e por quê:** 40 combinações, quase todas de 2023
em diante, porque **o MTE não publicou layout de 2023 para frente** — o
mais novo no FTP é o de 2020. A maior é `categoria_trabalhador` (22
códigos, 262 milhões de linhas), a tabela de categorias do eSocial. Também
faltam `tipo_estab` 5 e 6 (16 milhões, 2018-2025 — provavelmente CAEPF e
CNO, que substituíram o CEI, mas isso é inferência e ficou fora do
dicionário), `causa_afastamento_1` 80/85/90 e seis códigos novos de
`motivo_desligamento`.

**Correções nas próprias checagens:**

- `coerencia_com_salario_minimo` tinha **faixa errada e série quebrada**. A
  faixa documentada (1,3 a 1,6 SM) é do Nordeste; no Brasil a mediana dá
  **1,81 a 1,99** em todos os anos, e a checagem dispararia falso alarme em
  qualquer rodada nacional. Pior: ela não filtrava `remun > 0`, então
  herdava a ruptura de 2023 e **saltava sozinha de 1,76 para 1,88** na
  virada 2022/2023. Com o filtro, a descontinuidade some (1,89 → 1,88) — a
  evidência mais direta de que a ruptura de 2023 fica inteiramente
  resolvida quando os zeros são tratados.
- `anomalia_ano_uf` estava afogada pela pseudo-UF `NI`
  (`RAIS_VINC_PUB_NI`, vínculo sem município), que tem de 16 a 16 mil
  linhas e varia 14.512% ou −62% por ano sem nada de errado. A regra dos
  25% agora só vale para partição com 50 mil linhas ou mais, e a `NI` sai
  listada à parte como "partição minúscula", sem sumir do relatório.
- `codigos` varria a base **três vezes** com o mesmo SQL — no `COPY`, na
  contagem e no top 30. Com a base nacional no USB isso passa de uma hora
  por varredura. Agora materializa uma vez numa tabela temporária.

**Nenhuma checagem pega arquivo corrompido na origem.** O `.7z` quebrado do
`RAIS/2019/Legado` passa em três camadas: o tamanho bate com o do FTP, o
`py7zr.test()` só confere o CRC do cabeçalho, e o `criar`/`checar` nunca
vêem o problema porque a unidade simplesmente não entra na árvore. **Só a
descompactação completa pega** — que é exatamente o que o
`pdet_verifica.py` foi reescrito para fazer. E **rebaixar não conserta**:
o MD5 do arquivo rebaixado é idêntico.

### Armadilhas de operação dos scripts (não são bugs de dado)

- **`--meta` quer uma pasta só, mas os CSVs de proveniência estão em dois
  lugares**: `dicionarios/dic_rais.csv`, `estado/inventario_ftp.csv` e
  `estado/cabecalhos.csv` no repositório; `conversao.csv` e
  `manifesto.csv` em `<dados>/03_meta`. Montar uma pasta com links para
  os cinco resolve.
- **`pdet_verifica.py --manifesto` só aceita `conversao.csv`**, que tem a
  coluna `arquivo`. Passar o `manifesto.csv` do download (coluna
  `arquivo_local`) dá `KeyError`.
- **`$p.ExitCode` volta vazio quando se usa `Start-Process` com
  `-RedirectStandardOutput`.** Uma condição `if ($p.ExitCode -ne 0)` lê o
  vazio como falha e para a fila inteira depois de um ano que deu certo.
  O sinal confiável é o próprio script dizer que terminou, mais o stderr
  vazio:

  ```powershell
  $ok = (Test-Path $saida) -and
        (Select-String -Path $saida -Pattern 'Cubos prontos em' -Quiet)
  ```
- **`refazer_download.txt` só é reescrito quando há algo a refazer.** Uma
  verificação limpa deixa o arquivo antigo intacto, então um
  `refazer_download.txt` presente **não** significa que há pendências —
  conferir a data.

**Ambiente FTP do MTE:** o servidor tem instabilidade documentada e
proteção antiflood — crawling agressivo pode gerar bloqueio temporário de
IP.

## 6. Divergências resolvidas (ficam registradas para não voltarem)

Todas as divergências que este documento carregava até 31/08 foram fechadas
na rodada de 02/09, sobre a base nacional completa.

- **"281 de 293 unidades RAIS_VINCULOS convertidas, 6 falhando na pasta
  definitiva"** — **não procede.** O manifesto tem 284 arquivos RAIS da
  pasta definitiva e o `E:\pdet\03_meta\conversao.csv` tem 284 unidades,
  todas `ok`. Os 6 `LZMAError` eram arquivos de `NOVO CAGED\Legado\
  Estabelecimentos` rotulados `RAIS_ESTAB` pelo bug de classificação por
  caminho, e estão corrompidos na origem. Ver 4.1.

- **Qual `conversao.csv` vale** — o de `E:\pdet\03_meta` (284 linhas,
  todas `ok`). O da raiz do repositório é a fotografia pré-correção, com
  485 linhas e 198 erros. Ele foi mantido só como registro do bug; **não
  aponte `--meta` para uma pasta que contenha ele**, porque o `criar`
  escolhe a pasta que tiver mais CSVs de apoio e vai preferir a raiz do
  projeto. Monte uma pasta só, como `C:\pdet\meta`, com o `conversao.csv`
  bom e os quatro do repositório (`manifesto.csv`,
  `dicionarios/dic_rais.csv`, `estado/inventario_ftp.csv`,
  `estado/cabecalhos.csv`).

- **`pdet_banco.py`, `sql/consultas.sql` e os `dicionarios/dim_*.csv`**
  estão no repositório e versionados. A pendência não existe mais.

- **A armadilha do `--dicionarios` apontar para `dicionarios/` enquanto os
  `dim_*.csv` moravam na raiz** (registrada aqui até 03/09) não existe
  mais: a reorganização de 04/09 moveu os `dim_*.csv` (e `dic_rais.csv`)
  para `dicionarios/`, batendo com o default do script. Ver seção 8.

- **Gerenciador de ambiente**: o fluxo principal é `uv`
  (`pyproject.toml` + `uv.lock`), com conda como intérprete alternativo
  nos launchers.

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

4. **02/09/2026 — retomada com a base nacional completa (Windows)**:
   checagem 13/13 sobre 44,7 GB, morte das suspeitas de duplicação e das
   "quedas verticais", conferência do `dim_codigos.csv` contra os layouts
   oficiais (descoberta do deslocamento da faixa de remuneração de
   dezembro e da mudança de escala da média em 2023), corrupção dos
   arquivos `Legado` de 2019 no servidor do MTE, e a resposta da pergunta
   das vintages: o Legado 2023 reproduz os 54.706.385 oficiais, e a
   revisão da definitiva é quase toda administração pública.

## 8. Estrutura do repositório

Reorganizado em 04/09/2026 para ficar legível como repositório GitHub
(antes disso, os ~40 arquivos ficavam soltos na raiz). Os scripts `.py` e
os launchers (`pdet.ps1`, `pdet.sh`, `pdet-setup.ps1`) continuam na raiz
— é onde eles já esperavam se encontrar entre si. O que mudou de lugar:

- `dicionarios/` — tabelas de referência editadas à mão: `dic_rais.csv`,
  `dim_ano.csv`, `dim_cnae_classe.csv`, `dim_cnae_subclasse.csv`,
  `dim_codigos.csv`, `dim_municipio.csv`. É também o default de
  `pdet_banco.py criar --dicionarios` — antes esse default apontava para
  uma pasta que não existia (ver a armadilha resolvida na seção 5/6);
  agora bate.
- `sql/` — `consultas.sql`.
- `estado/` — saída gerada pelo pipeline, continua versionada:
  `inventario_ftp.csv`, `inventario_state.json`, `cabecalhos.csv`,
  `cabecalhos.md`, `colunas_sugestao.csv`, `checagem_banco.md`,
  `refazer_download.txt`, `relatorio_fase0.md`.
- `docs/` — `COMO-RODAR-BANCO.txt`, `RAIS_MAC.md`, e `docs/historico/`
  para notas de rodadas superadas (`analise_checagem.md`,
  `checagem_banco_mac.md`, ambas de 13/08, com achados já absorvidos na
  seção 6 deste documento).
- `COMO-RODAR.txt` saiu do controle de versão — é gerado por
  `pdet-setup.ps1` com o caminho pessoal desta máquina embutido no
  conteúdo, não é dado do projeto.

Todos os defaults de argparse dos scripts (`--dic`, `--inventario`,
`--arquivo` de `consulta`, saída de `checar`, etc.) foram atualizados
para os novos caminhos. `CLAUDE.md` e `RETOMAR.md` continuam na raiz —
são os dois documentos que qualquer sessão nova precisa achar primeiro.
