-- ===========================================================================
-- PDET / RAIS - consultas nomeadas
-- ===========================================================================
-- Rode com:
--     python pdet_banco.py consulta --banco C:\pdet\pdet.duckdb --listar
--     python pdet_banco.py consulta --banco ... --nome estoque_uf_ano
--     python pdet_banco.py consulta --banco ... --nome estoque_municipio ^
--         --param uf=PI --param ano=2025 --csv estoque_pi_2025.csv
--
-- Parametros aparecem como ${nome} e sao trocados por --param nome=valor.
-- As consultas que comecam com "chk_" leem o Parquet direto (lentas, para
-- validacao). As demais leem os cubos materializados (instantaneas).
-- ===========================================================================


-- @nome: estoque_brasil
-- @desc: Serie do emprego formal no Brasil: estoque em 31/12, fluxo e massa.
SELECT ano,
       sum(ativos)                                       AS estoque_3112,
       sum(ativos) - lag(sum(ativos)) OVER (ORDER BY ano) AS variacao_absoluta,
       round(100.0 * (sum(ativos) / nullif(lag(sum(ativos))
             OVER (ORDER BY ano), 0) - 1), 2)            AS variacao_pct,
       sum(admitidos)                                    AS admissoes,
       sum(desligados)                                   AS desligamentos,
       sum(admitidos) - sum(desligados)                  AS saldo,
       round(sum(massa_dez) / 1e9, 2)                    AS massa_dez_bilhoes,
       round(sum(massa_dez) / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media
FROM fato_vinc_mun
GROUP BY ano ORDER BY ano;


-- @nome: estoque_uf_ano
-- @desc: Estoque por UF em cada ano, com variacao anual e participacao no pais.
SELECT ano, uf, uf_nome, regiao, ativos AS estoque_3112,
       round(100.0 * (ativos / nullif(lag(ativos)
             OVER (PARTITION BY uf ORDER BY ano), 0) - 1), 2) AS var_pct,
       round(100.0 * ativos / sum(ativos) OVER (PARTITION BY ano), 2)
           AS part_brasil_pct,
       admitidos, desligados, saldo,
       round(remun_dez_media, 2)      AS remun_dez_media,
       round(remun_dez_media_real, 2) AS remun_dez_media_real
FROM v_uf_ano
ORDER BY uf, ano;


-- @nome: estoque_municipio
-- @desc: Municipios de uma UF num ano. Parametros: uf, ano.
SELECT cod_mun, nome_mun, reg_intermediaria, reg_imediata,
       ativos AS estoque_3112, admitidos, desligados, saldo,
       pct_fem, pct_publico,
       round(remun_dez_media, 2)      AS remun_dez_media,
       round(remun_dez_media_sm, 2)   AS remun_em_salarios_minimos,
       round(remun_dez_p50, 2)        AS remun_dez_mediana
FROM v_municipio_ano
WHERE uf = '${uf}' AND ano = ${ano}
ORDER BY ativos DESC;


-- @nome: municipio_serie
-- @desc: Serie historica completa de um municipio. Parametro: cod_mun (6 digitos).
SELECT ano, nome_mun, uf,
       ativos AS estoque_3112,
       ativos - lag(ativos) OVER (ORDER BY ano) AS variacao,
       round(100.0 * (ativos / nullif(lag(ativos) OVER (ORDER BY ano), 0) - 1), 2)
           AS var_pct,
       admitidos, desligados, saldo,
       round(remun_dez_media, 2)      AS remun_nominal,
       round(remun_dez_media_real, 2) AS remun_real,
       ano_base_deflator,
       pct_fem, pct_publico, round(idade_media, 1) AS idade_media
FROM v_municipio_ano
WHERE cod_mun = '${cod_mun}'
ORDER BY ano;


-- @nome: ranking_crescimento
-- @desc: Municipios de uma UF que mais ganharam e perderam vinculos entre dois anos. Parametros: uf, ano_ini, ano_fim.
WITH a AS (SELECT cod_mun, nome_mun, ativos FROM v_municipio_ano
           WHERE uf = '${uf}' AND ano = ${ano_ini}),
     b AS (SELECT cod_mun, ativos FROM v_municipio_ano
           WHERE uf = '${uf}' AND ano = ${ano_fim})
SELECT a.cod_mun, a.nome_mun,
       a.ativos AS estoque_${ano_ini}, b.ativos AS estoque_${ano_fim},
       b.ativos - a.ativos AS variacao,
       round(100.0 * (b.ativos / nullif(a.ativos, 0) - 1), 1) AS var_pct
FROM a JOIN b USING (cod_mun)
ORDER BY variacao DESC;


-- @nome: setor_uf
-- @desc: Estoque por secao da CNAE numa UF, serie historica. Parametro: uf.
SELECT ano, cnae_secao, any_value(desc_secao) AS setor,
       sum(ativos) AS estoque_3112,
       round(100.0 * sum(ativos) / sum(sum(ativos)) OVER (PARTITION BY ano), 1)
           AS part_pct,
       sum(saldo) AS saldo,
       round(sum(massa_dez) / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media
FROM v_setor_ano
WHERE uf = '${uf}'
GROUP BY ano, cnae_secao
ORDER BY ano, estoque_3112 DESC;


-- @nome: setor_municipio
-- @desc: Composicao setorial de um municipio num ano. Parametros: cod_mun, ano.
SELECT cnae_secao, any_value(desc_secao) AS setor,
       sum(ativos) AS estoque_3112,
       round(100.0 * sum(ativos) / sum(sum(ativos)) OVER (), 1) AS part_pct,
       sum(admitidos) AS admissoes, sum(desligados) AS desligamentos,
       sum(saldo) AS saldo,
       round(sum(massa_dez) / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media
FROM v_setor_ano
WHERE cod_mun = '${cod_mun}' AND ano = ${ano}
GROUP BY cnae_secao
ORDER BY estoque_3112 DESC;


-- @nome: remuneracao_real
-- @desc: Remuneracao media de dezembro em valores reais, por UF. Mostra se o poder de compra subiu ou caiu.
SELECT ano, uf, uf_nome,
       round(remun_dez_media, 2)      AS nominal,
       round(remun_dez_media_real, 2) AS real_base_recente,
       round(100.0 * (remun_dez_media_real / nullif(lag(remun_dez_media_real)
             OVER (PARTITION BY uf ORDER BY ano), 0) - 1), 2) AS var_real_pct
FROM v_uf_ano
ORDER BY uf, ano;


-- @nome: hiato_sexo
-- @desc: Diferenca de remuneracao entre homens e mulheres, por UF e ano.
SELECT ano, uf,
       sum(ativos) FILTER (WHERE sexo = 1) AS ativos_homens,
       sum(ativos) FILTER (WHERE sexo = 2) AS ativos_mulheres,
       round(sum(massa_dez) FILTER (WHERE sexo = 1)
             / nullif(sum(ativos_com_remun) FILTER (WHERE sexo = 1), 0), 2)
           AS remun_homens,
       round(sum(massa_dez) FILTER (WHERE sexo = 2)
             / nullif(sum(ativos_com_remun) FILTER (WHERE sexo = 2), 0), 2)
           AS remun_mulheres,
       round(100.0 * (
             (sum(massa_dez) FILTER (WHERE sexo = 2)
              / nullif(sum(ativos_com_remun) FILTER (WHERE sexo = 2), 0))
           / nullif(sum(massa_dez) FILTER (WHERE sexo = 1)
              / nullif(sum(ativos_com_remun) FILTER (WHERE sexo = 1), 0), 0)
             - 1), 1)
           AS hiato_pct
FROM fato_vinc_perfil
GROUP BY ano, uf
ORDER BY uf, ano;


-- @nome: perfil_instrucao
-- @desc: Estoque e remuneracao por grau de instrucao numa UF e ano. Parametros: uf, ano.
SELECT grau_instrucao, any_value(instrucao_rot) AS instrucao,
       sum(ativos) AS estoque_3112,
       round(100.0 * sum(ativos) / sum(sum(ativos)) OVER (), 1) AS part_pct,
       round(sum(massa_dez) / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media
FROM v_perfil_ano
WHERE uf = '${uf}' AND ano = ${ano}
GROUP BY grau_instrucao
ORDER BY grau_instrucao;


-- @nome: perfil_raca_sexo
-- @desc: Cruzamento raca/cor por sexo numa UF e ano. Parametros: uf, ano.
SELECT raca_rot AS raca_cor, sexo_rot AS sexo,
       sum(ativos) AS estoque_3112,
       round(sum(massa_dez) / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media
FROM v_perfil_ano
WHERE uf = '${uf}' AND ano = ${ano}
GROUP BY raca_rot, sexo_rot, raca_cor, sexo
ORDER BY raca_cor, sexo;


-- @nome: fluxo_mensal
-- @desc: Admissoes e desligamentos mes a mes numa UF. Parametros: uf, ano.
SELECT mes, sum(admissoes) AS admissoes, sum(desligamentos) AS desligamentos,
       sum(admissoes) - sum(desligamentos) AS saldo,
       sum(sum(admissoes) - sum(desligamentos)) OVER (ORDER BY mes)
           AS saldo_acumulado
FROM fato_vinc_fluxo_mes
WHERE uf = '${uf}' AND ano = ${ano}
GROUP BY mes ORDER BY mes;


-- @nome: emprego_publico
-- @desc: Peso do setor publico no emprego formal, por UF e ano.
SELECT ano, uf, sum(ativos) AS estoque_3112,
       sum(ativos_publico) AS estoque_publico,
       round(100.0 * sum(ativos_publico) / nullif(sum(ativos), 0), 1) AS pct_publico
FROM fato_vinc_mun
GROUP BY ano, uf ORDER BY uf, ano;


-- @nome: porte_estabelecimento
-- @desc: Estabelecimentos e vinculos por porte numa UF e ano. Parametros: uf, ano.
SELECT e.tamanho_estab, coalesce(d.rotulo, '?') AS porte,
       sum(e.estabelecimentos) AS estabelecimentos,
       sum(e.vinculos_ativos)  AS vinculos_ativos,
       round(100.0 * sum(e.vinculos_ativos) / sum(sum(e.vinculos_ativos)) OVER (), 1)
           AS part_vinculos_pct
FROM fato_estab_mun e
LEFT JOIN dim_codigos d ON d.variavel = 'tamanho_estab'
                       AND d.codigo = CAST(e.tamanho_estab AS VARCHAR)
WHERE e.uf = '${uf}' AND e.ano = ${ano}
GROUP BY e.tamanho_estab, d.rotulo
ORDER BY e.tamanho_estab;


-- @nome: top_ocupacoes
-- @desc: Ocupacoes (CBO) mais frequentes num municipio. Exige --uf-detalhe na agregacao. Parametros: cod_mun, ano.
SELECT cbo_2002, sum(ativos) AS estoque_3112,
       round(sum(ativos_com_remun * remun_dez_media)
             / nullif(sum(ativos_com_remun), 0), 2)
           AS remun_dez_media,
       sum(admitidos) AS admissoes
FROM fato_vinc_ocupacao
WHERE cod_mun = '${cod_mun}' AND ano = ${ano}
GROUP BY cbo_2002
ORDER BY estoque_3112 DESC
LIMIT 50;


-- @nome: capitais_nordeste
-- @desc: Serie comparada do estoque nas capitais do Nordeste.
SELECT ano, nome_mun, uf, ativos AS estoque_3112,
       round(100.0 * (ativos / nullif(lag(ativos)
             OVER (PARTITION BY cod_mun ORDER BY ano), 0) - 1), 1) AS var_pct,
       round(remun_dez_media_real, 2) AS remun_real
FROM v_municipio_ano
WHERE cod_mun IN ('211130',  -- Sao Luis
                  '221100',  -- Teresina
                  '230440',  -- Fortaleza
                  '240810',  -- Natal
                  '250750',  -- Joao Pessoa
                  '261160',  -- Recife
                  '271490',  -- Maceio
                  '280030',  -- Aracaju
                  '292740')  -- Salvador
ORDER BY nome_mun, ano;


-- ===========================================================================
-- Validacao - leem o Parquet direto. Sao lentas de proposito.
-- ===========================================================================

-- @nome: chk_estoque_direto
-- @desc: VALIDACAO Recalcula o estoque a partir do Parquet e compara com o cubo.
WITH direto AS (
  SELECT ano, count(*) FILTER (WHERE vinculo_ativo_3112) AS ativos_parquet
  FROM vinculos GROUP BY ano),
cubo AS (SELECT ano, sum(ativos) AS ativos_cubo FROM fato_vinc_mun GROUP BY ano)
SELECT ano, ativos_parquet, ativos_cubo,
       ativos_cubo - ativos_parquet AS diferenca
FROM direto FULL JOIN cubo USING (ano) ORDER BY ano;


-- @nome: chk_uma_uf_um_ano
-- @desc: VALIDACAO Le uma particao so e mostra tudo que ha nela. Parametros: uf, ano.
SELECT count(*)                                             AS linhas,
       count(*) FILTER (WHERE vinculo_ativo_3112)           AS ativos,
       count(DISTINCT cod_mun)                              AS municipios,
       count(DISTINCT cnae20_classe)                        AS classes_cnae,
       min(remun_dez_nom)                                   AS remun_min,
       round(median(remun_dez_nom)
             FILTER (WHERE remun_dez_nom > 0), 2)           AS remun_mediana,
       max(remun_dez_nom)                                   AS remun_max,
       round(avg(idade), 1)                                 AS idade_media
FROM vinculos WHERE uf = '${uf}' AND ano = ${ano};


-- @nome: chk_amostra
-- @desc: VALIDACAO 20 linhas cruas de uma particao, para olhar com o olho. Parametros: uf, ano.
SELECT ano, uf, cod_mun, sexo, idade, grau_instrucao, cbo_2002,
       cnae20_classe, tipo_vinculo, vinculo_ativo_3112,
       mes_admissao, mes_desligamento, qtd_hora_contr,
       remun_dez_nom, remun_media_nom, tempo_emprego
FROM vinculos WHERE uf = '${uf}' AND ano = ${ano} LIMIT 20;


-- @nome: chk_colunas_por_ano
-- @desc: VALIDACAO Preenchimento (%) das colunas que so existem em alguns layouts. 0% ou coluna ausente = nao existe naquele ano.
-- COLUMNS(regex) so expande para as colunas que existem de fato, entao a
-- consulta nao quebra quando um ano nao tem a coluna.
SELECT ano,
       round(100.0 * COUNT(COLUMNS('^(ibge_subsetor|remun_janeiro_nom|ano_chegada_brasil|ind_trab_parcial|ind_trab_intermitente|tipo_salario|salario_contratual|categoria_trabalhador|ind_vinculo_abandonado)$'))
             / count(*), 1)
FROM vinculos GROUP BY ano ORDER BY ano;


-- @nome: chk_preenchimento_geral
-- @desc: VALIDACAO Preenchimento (%) de TODAS as colunas de vinculos, ano a ano. Le muita coluna: demora.
SELECT ano, round(100.0 * COUNT(COLUMNS(*)) / count(*), 1)
FROM vinculos GROUP BY ano ORDER BY ano;
