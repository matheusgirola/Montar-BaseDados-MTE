# Leitura do checagem_banco.md de 13/08 (rodada com apoio incompleto)

## Resumo

A duplicacao suspeitada na secao 4 do CLAUDE.md **nao aparece nos dados**.
Mas o relatorio que foi gerado nao tinha autoridade para dizer isso: 5 das
12 checagens nao chegaram a rodar. Este documento separa o que ja esta
respondido do que continua em aberto.

## 1. Por que 5 checagens morreram

Nao foi erro de dado. Foi caminho errado no `criar`:

| Checagem | Faltou | Onde o arquivo realmente esta |
|---|---|---|
| 3 conferencia_com_manifesto | `meta_conversao` | `conversao.csv` fica na raiz de dados (`E:\pdet`), nao no projeto |
| 5 municipio_sem_ibge | `dim_municipio` | `dim_municipio.csv` esta na RAIZ do projeto |
| 6 uf_incoerente | `dim_municipio` | idem |
| 7 cnae_sem_dicionario | `dim_cnae_classe` | `dim_cnae_classe.csv`, raiz do projeto |
| 10 coerencia_com_salario_minimo | `dim_ano` | `dim_ano.csv`, raiz do projeto |

O `COMO-RODAR-BANCO.txt` mandava passar `--dicionarios .\dicionarios`, e o
default do argumento tambem era `dicionarios` -- mas os cinco `dim_*.csv`
estao na raiz do pacote, nao em uma subpasta. A funcao `carregar_csv`
devolvia `False` em silencio para arquivo inexistente e o `criar` seguia
adiante. Que `meta_colunas`, `meta_inventario` e `meta_cabecalhos`
carregaram (aparecem nas sugestoes "Did you mean") confirma o diagnostico:
`--meta .` achou os tres CSVs que moram no projeto e nao achou os dois que
moram junto dos dados.

## 2. O que ja esta respondido: nao ha duplicacao no agregado nacional

A checagem 4 (`estoque_brasil`) bate com a RAIS publicada na casa da
unidade, nao na ordem de grandeza:

| ano | ativos_3112 no banco | RAIS publicada |
|---|---|---|
| 2010 | 44.068.355 | 44.068.355 |
| 2014 | 49.571.510 | ~49,57 mi |
| 2019 | 46.716.492 | ~46,72 mi |

Uma duplicacao de arquivo inflaria essa serie de forma visivel. Ela nao
esta inflada. Some-se a isso a checagem 2 (`particao_com_varias_origens`)
sem ocorrencias, e a hipotese de "conversao duplicada" fica sem
sustentacao para o conjunto da base.

**A checagem 2 valia mesmo?** Ela extraia o token da unidade de conversao
do caminho do Parquet com `regexp_extract(filename, 'u([0-9a-f]+)_', 1)`.
Testado contra o layout real (`E:/pdet/10_parquet/rais_vinculos/ano=2014/
uf=AC/u<token>_<uuid>.parquet`), o padrao devolve o token certo -- entao o
"sem ocorrencias" foi resultado de verdade, nao artefato. O padrao era
fragil, porem: aplicado ao caminho inteiro ele casa antes com o `ue` de uma
pasta como `/dados_ue_2/` ou com o `uf` de `/uf=AC/uf_AC/`, devolveria o
mesmo lixo para todos os arquivos, `count(DISTINCT)` daria 1 e a checagem
passaria sempre. Isso foi corrigido (ver secao 5).

## 3. O que continua em aberto

**a) A anomalia AC/AP 2014 nao foi verificada.** A checagem 1 foi cortada
em 40 linhas -- parou em AM 2017. AP nunca apareceu no relatorio. A
comparacao que motivou toda a investigacao nao chegou a ser impressa.

**b) A conferencia com o `conversao.csv` nunca rodou.** E a unica checagem
que compara linha a linha o que esta no Parquet com o que a conversao diz
ter escrito. E tambem a que detectaria arquivo movido ou apagado da arvore
final -- coisa que as contagens agregadas nao pegam.

**c) Divergencia entre as checagens 4 e 12 a partir de 2023.** A soma de
`qtd_vinculos_ativos` declarada pelos estabelecimentos nao fecha com a
contagem de vinculos ativos:

| ano | ativos (check 4) | soma declarada (check 12) | diferenca |
|---|---|---|---|
| 2010-2022 | -- | -- | zero, exata |
| 2023 | 55.818.007 | 55.247.863 | -570.144 |
| 2024 | 57.800.651 | 57.061.992 | -738.659 |
| 2025 | 60.691.770 | 59.892.402 | -799.368 |

Treze anos fechando na unidade e depois tres anos divergindo indica que a
quebra de formato de 2023 tambem atingiu a base de estabelecimentos.
Vale conferir antes de publicar qualquer numero de estabelecimento pos-2023.

**d) Estabelecimentos saltam 39% em 2023** (8,45 mi -> 11,77 mi), e a RAIS
negativa 79% (4,00 mi -> 7,18 mi). Parte disso e real (mudanca de coleta
via eSocial), mas a magnitude merece confirmacao contra a publicacao do
MTE antes de virar serie historica.

**e) Nulos em `remun_dez_nom` a partir de 2023** (38,6% / 40,0% / 41,8%).
Isso NAO parece bug: e a contrapartida dos marcadores `999999`/`999997`
virando NULL. Repare na checagem 9: ate 2022 havia 2 a 4 milhoes de
`zerados` por ano; de 2023 em diante sao zero. O vinculo desligado, que
antes entrava como 0, agora entra como NULL. O efeito pratico e que
qualquer contagem de "remuneracao zerada" ou media que trate 0 como valor
quebra na juncao 2022/2023 -- as consultas precisam usar
`WHERE vinculo_ativo_3112`, como a checagem 9 ja faz.

## 4. Ordem sugerida

1. Rodar `criar` de novo com `--dicionarios .` e `--meta E:\pdet`. O script
   agora aborta se nao achar os CSVs, em vez de seguir em silencio.
2. Rodar `--limite 0 checar` e ler o bloco "## Resumo": so seguir quando
   ele disser 13 de 13.
3. Olhar a checagem 3 (`anomalia_ano_uf`), que e curta e responde direto
   sobre AC/AP 2014 e sobre as quedas de MT 2011, RS 2012, SP 2015,
   CE 2016 e SP 2024.
4. Olhar a checagem 4 (`conferencia_com_manifesto`), que agora tem o
   `conversao.csv` para comparar.
5. So entao `codigos` e `agregar`.

## 5. Mudancas feitas no codigo

- `pdet_banco.py` `criar`: procura os CSVs de apoio na pasta pedida, depois
  na pasta do script, depois no diretorio atual; lista o que faltou e
  aborta (`--parcial` aceita de proposito o banco incompleto).
- `pdet_banco.py` `checar`: checagem com dependencia ausente e marcada
  PULADA, nao FALHOU, e o relatorio ganha um "## Resumo" no topo com
  quantas de fato rodaram.
- Checagem 2: token extraido do nome do arquivo, ancorado em
  `^u([0-9a-f]{10})_`, e partitions com token vazio agora sao reportadas
  em vez de passarem batido.
- Nova checagem `anomalia_ano_uf`: contagem identica entre UFs no mesmo ano
  e variacao anual acima de 25%.
- `--limite 0` gera o relatorio sem corte; o aviso de corte diz como.
- `COMO-RODAR-BANCO.txt`: caminhos corrigidos e explicados.
