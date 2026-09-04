#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 3 - Banco analitico DuckDB sobre o Parquet da RAIS
========================================================

O Parquet no HD externo continua sendo a fonte da verdade. Este script cria
um arquivo .duckdb PEQUENO no disco interno contendo:

  * VIEWS que apontam para o Parquet (nada e copiado)
  * DIMENSOES carregadas de CSV (municipio IBGE, CNAE, codigos da RAIS,
    salario minimo e deflator IPCA)
  * METADADOS de proveniencia (o que foi baixado, o que foi convertido,
    qual coluna existe em qual ano)
  * CUBOS materializados - as agregacoes que os relatorios anuais usam,
    reconstruiveis ano a ano

O arquivo .duckdb pode ser apagado e refeito a qualquer momento. Nenhum dado
original vive dentro dele.

USO
---
    # 1) cria/atualiza views, dimensoes e metadados (segundos)
    python pdet_banco.py criar --parquet E:\\pdet\\10_parquet ^
        --banco C:\\pdet\\pdet.duckdb --dicionarios .\\dicionarios ^
        --meta .\\  --tmp C:\\pdet\\tmp

    # 2) bateria de integridade ANTES de agregar (minutos)
    python pdet_banco.py --banco C:\\pdet\\pdet.duckdb checar

    # 3) codigos observados x rotulados (ajuda a completar dim_codigos.csv)
    python pdet_banco.py --banco C:\\pdet\\pdet.duckdb codigos 

    # 4) materializa os cubos (horas na primeira vez)
    python pdet_banco.py agregar --banco C:\\pdet\\pdet.duckdb --uf-detalhe PI

    # ... e no ano seguinte, so o ano novo:
    python pdet_banco.py agregar --banco C:\\pdet\\pdet.duckdb --ano 2026

    # 5) consultas nomeadas do arquivo consultas.sql
    python pdet_banco.py consulta --banco C:\\pdet\\pdet.duckdb --listar
    python pdet_banco.py consulta --banco C:\\pdet\\pdet.duckdb ^
        --nome estoque_uf_ano --csv saida.csv

Dependencia: duckdb.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASES = {
    "RAIS_VINCULOS": "rais_vinculos",
    "RAIS_ESTAB": "rais_estab",
    "RAIS_DOMESTICO": "rais_domestico",
}

DIMENSOES = {
    "dim_municipio": "dim_municipio.csv",
    "dim_cnae_classe": "dim_cnae_classe.csv",
    "dim_cnae_subclasse": "dim_cnae_subclasse.csv",
    "dim_codigos": "dim_codigos.csv",
    "dim_ano": "dim_ano.csv",
}

# CSVs do projeto que viram tabelas de proveniencia dentro do banco.
METADADOS = {
    "meta_colunas": "dic_rais.csv",
    "meta_conversao": "conversao.csv",
    "meta_download": "manifesto.csv",
    "meta_inventario": "inventario_ftp.csv",
    "meta_cabecalhos": "cabecalhos.csv",
}


# ===========================================================================
# Utilitarios
# ===========================================================================

def p(caminho: Path | str) -> str:
    """Caminho no formato que o DuckDB entende em qualquer sistema."""
    return Path(caminho).as_posix()


def fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def abrir(banco: str, memoria: float, threads: int, tmp: str,
          leitura: bool = False):
    import duckdb
    Path(banco).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(banco, read_only=leitura)
    con.execute(f"SET memory_limit='{memoria:.1f}GB'")
    if threads:
        con.execute(f"SET threads={threads}")
    con.execute("SET preserve_insertion_order=false")
    if tmp:
        Path(tmp).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{p(tmp)}'")
    return con


def config_ler(con, chave: str, padrao: str = "") -> str:
    try:
        r = con.execute("SELECT valor FROM meta_config WHERE chave = ?",
                        [chave]).fetchone()
    except Exception:                                        # noqa: BLE001
        return padrao
    return r[0] if r else padrao


def config_gravar(con, chave: str, valor: str) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS meta_config
                   (chave VARCHAR PRIMARY KEY, valor VARCHAR,
                    atualizado_em VARCHAR)""")
    con.execute("""INSERT OR REPLACE INTO meta_config VALUES (?, ?, ?)""",
                [chave, valor, agora()])


def tabela_existe(con, nome: str) -> bool:
    r = con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?",
        [nome]).fetchone()
    return bool(r and r[0])


def objeto_existe(con, nome: str) -> bool:
    """Tabela OU view - as bases (vinculos, estabelecimentos) sao views."""
    if tabela_existe(con, nome):
        return True
    r = con.execute(
        "SELECT count(*) FROM duckdb_views() WHERE view_name = ?",
        [nome]).fetchone()
    return bool(r and r[0])


def imprimir(con, sql: str, limite: int = 40) -> None:
    """Mostra o resultado de uma consulta como tabela de texto."""
    rel = con.sql(sql)
    cols = rel.columns
    linhas = rel.fetchmany(limite)
    if not linhas:
        print("  (sem linhas)")
        return
    def cel(v):
        if v is None:
            return "-"
        if isinstance(v, float):
            return f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        if isinstance(v, int):
            # ano e codigo nao levam separador de milhar
            return f"{v:,}".replace(",", ".") if abs(v) >= 10000 else str(v)
        return str(v)
    corpo = [[cel(v) for v in ln] for ln in linhas]
    larg = [max(len(c), *(len(l[i]) for l in corpo))
            for i, c in enumerate(cols)]
    print("  " + "  ".join(c.ljust(larg[i]) for i, c in enumerate(cols)))
    print("  " + "  ".join("-" * w for w in larg))
    for l in corpo:
        print("  " + "  ".join(v.rjust(larg[i]) if v.replace(".", "")
                               .replace(",", "").replace("-", "").isdigit()
                               else v.ljust(larg[i])
                               for i, v in enumerate(l)))
    if len(linhas) == limite:
        print(f"  ... (cortado em {limite} linhas)")


# ===========================================================================
# criar - views, dimensoes, metadados
# ===========================================================================

def colunas_do_parquet(con, glob: str) -> list[str]:
    """Le o cabecalho de UM arquivo para saber se ano/uf estao gravados
    dentro do Parquet ou so no nome da pasta."""
    try:
        arqs = con.execute("SELECT file FROM glob(?) LIMIT 1",
                           [glob]).fetchall()
    except Exception:                                        # noqa: BLE001
        return []
    if not arqs:
        return []
    # hive_partitioning = false: sem isso o DuckDB inventa as colunas ano/uf
    # a partir do nome da pasta e o teste abaixo sempre daria positivo.
    d = con.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = false) "
        "LIMIT 0", [arqs[0][0]]).fetchall()
    return [x[0] for x in d]


def criar_views(con, raiz: Path, verboso: bool = True) -> dict:
    """Uma view 'src_*' crua por base e uma view enriquecida por cima."""
    achadas = {}
    for base, pasta in BASES.items():
        # "[!.]" descarta os AppleDouble ("._nome.parquet") que o macOS cria
        # ao gravar em exFAT: eles casam com *.parquet e o DuckDB morre com
        # "No magic bytes found at end of file". Inocuo em Linux/Windows.
        glob = f"{p(raiz / pasta)}/**/[!.]*.parquet"
        cols = colunas_do_parquet(con, glob)
        if not cols:
            if verboso:
                print(f"  {base:16s} nenhum Parquet em {raiz / pasta}")
            continue

        # Se ano/uf ja estao dentro do arquivo, nao pode reler pela pasta.
        dentro = {"ano", "uf"} & set(cols)
        if dentro:
            leitura = (f"read_parquet('{glob}', union_by_name = true)")
            proj = "*"
        else:
            leitura = (f"read_parquet('{glob}', hive_partitioning = true, "
                       f"union_by_name = true)")
            proj = ("* EXCLUDE (ano, uf), CAST(ano AS SMALLINT) AS ano, "
                    "CAST(uf AS VARCHAR) AS uf")

        con.execute(f"CREATE OR REPLACE VIEW src_{pasta} AS "
                    f"SELECT {proj} FROM {leitura}")
        # view separada, com o nome do arquivo de origem, so para diagnostico
        con.execute(
            f"CREATE OR REPLACE VIEW arq_{pasta} AS "
            f"SELECT * FROM read_parquet('{glob}', hive_partitioning = true, "
            f"union_by_name = true, filename = true)"
            if not dentro else
            f"CREATE OR REPLACE VIEW arq_{pasta} AS "
            f"SELECT * FROM read_parquet('{glob}', union_by_name = true, "
            f"filename = true)")
        achadas[base] = cols
        if verboso:
            print(f"  {base:16s} OK ({len(cols)} colunas no arquivo"
                  f"{', ano/uf gravados dentro' if dentro else ''})")

    if "RAIS_VINCULOS" in achadas:
        con.execute("""
            CREATE OR REPLACE VIEW vinculos AS
            SELECT v.*,
                   lpad(v.municipio, 6, '0')                       AS cod_mun,
                   try_cast(substr(lpad(v.cbo_2002, 6, '0'), 1, 1)
                            AS SMALLINT)                           AS cbo_grande_grupo,
                   try_cast(substr(lpad(v.natureza_juridica, 4, '0'), 1, 1)
                            AS SMALLINT)                           AS nat_jur_grupo,
                   substr(lpad(v.natureza_juridica, 4, '0'), 1, 1) = '1'
                                                                   AS setor_publico,
                   substr(lpad(v.cnae20_classe, 5, '0'), 1, 2)     AS cnae_divisao
            FROM src_rais_vinculos v
        """)
    if "RAIS_ESTAB" in achadas:
        con.execute("""
            CREATE OR REPLACE VIEW estabelecimentos AS
            SELECT e.*,
                   lpad(e.municipio, 6, '0')                       AS cod_mun,
                   try_cast(substr(lpad(e.natureza_juridica, 4, '0'), 1, 1)
                            AS SMALLINT)                           AS nat_jur_grupo,
                   substr(lpad(e.natureza_juridica, 4, '0'), 1, 1) = '1'
                                                                   AS setor_publico,
                   substr(lpad(e.cnae20_classe, 5, '0'), 1, 2)     AS cnae_divisao
            FROM src_rais_estab e
        """)
    if "RAIS_DOMESTICO" in achadas:
        con.execute("""
            CREATE OR REPLACE VIEW domesticos AS
            SELECT d.*, lpad(d.municipio, 6, '0') AS cod_mun
            FROM src_rais_domestico d
        """)
    return achadas


def carregar_csv(con, tabela: str, arquivo: Path):
    """Carrega um CSV de apoio em tabela real, TUDO como texto.

    Nao e preguica: 'cod_mun' vale 110001 e o detector de tipo o
    transformaria em numero, comendo o zero a esquerda de Rondonia e
    quebrando todo join com o municipio da RAIS. Os casts que importam
    ficam explicitos nas views."""
    if not arquivo.exists():
        return False
    con.execute(
        f"CREATE OR REPLACE TABLE {tabela} AS SELECT * FROM "
        f"read_csv('{p(arquivo)}', header = true, all_varchar = true, "
        f"sample_size = -1)")
    return True


def procurar_apoio(pedida: Path, arquivos) -> tuple[Path, list[str]]:
    """Acha a pasta que realmente tem os CSVs de apoio.

    O default de --dicionarios e' 'dicionarios' (onde os dim_*.csv moram
    no repositorio). Se o script for chamado de outro diretorio de trabalho
    e a pasta pedida nao tiver nenhum dos arquivos, tenta a pasta do script
    e o diretorio atual antes de desistir - senao o 'criar' segue adiante
    em silencio e metade das checagens morre depois com 'table does not
    exist'."""
    candidatas = [pedida, Path(__file__).resolve().parent, Path.cwd()]
    vistas, melhor, achados = [], pedida, []
    for c in candidatas:
        if c in vistas:
            continue
        vistas.append(c)
        tem = [n for n in arquivos if (c / n).exists()]
        if len(tem) > len(achados):
            melhor, achados = c, tem
        if len(achados) == len(arquivos):
            break
    return melhor, [n for n in arquivos if not (melhor / n).exists()]


def cmd_criar(a) -> None:
    raiz = Path(a.parquet)
    if not raiz.exists():
        sys.exit(f"ERRO: {raiz} nao existe. Aponte a raiz do Parquet "
                 f"(a pasta que contem rais_vinculos/, rais_estab/ ...).")

    con = abrir(a.banco, a.memoria, a.threads, a.tmp)
    print(f"Banco   : {a.banco}")
    print(f"Parquet : {raiz}\n")

    print("Views:")
    achadas = criar_views(con, raiz)
    if not achadas:
        sys.exit("\nERRO: nenhum Parquet encontrado. Confira --parquet.")

    print("\nDimensoes:")
    dic, faltando = procurar_apoio(Path(a.dicionarios), list(DIMENSOES.values()))
    if dic != Path(a.dicionarios):
        print(f"  (--dicionarios {a.dicionarios} nao tinha os CSVs; usando {dic})")
    for tabela, arq in DIMENSOES.items():
        ok = carregar_csv(con, tabela, dic / arq)
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0] if ok else 0
        print(f"  {tabela:22s} {'OK  ' + fmt(n) + ' linhas' if ok else 'AUSENTE (' + arq + ')'}")

    # UF sai de municipio: uma fonte so, sem risco de divergir
    if tabela_existe(con, "dim_municipio"):
        con.execute("""
            CREATE OR REPLACE TABLE dim_uf AS
            SELECT DISTINCT uf, cod_uf, uf_nome, regiao
            FROM dim_municipio WHERE uf IS NOT NULL AND uf <> ''
        """)
        n = con.execute("SELECT count(*) FROM dim_uf").fetchone()[0]
        print(f"  {'dim_uf':22s} OK  {n} linhas")
        # sentinelas: a RAIS usa codigos que o IBGE nao tem
        con.execute("""
            INSERT INTO dim_municipio (cod_mun, cod_mun7, nome_mun, uf, cod_uf,
                                       uf_nome, regiao, mesorregiao,
                                       microrregiao, reg_imediata,
                                       reg_intermediaria)
            SELECT cod_uf || '9999', NULL,
                   'Municipio nao identificado - ' || uf,
                   uf, cod_uf, uf_nome, regiao, NULL, NULL, NULL, NULL
            FROM dim_uf
            WHERE cod_uf || '9999' NOT IN
                  (SELECT cod_mun FROM dim_municipio WHERE cod_mun IS NOT NULL)
        """)
        con.execute("""
            INSERT INTO dim_municipio (cod_mun, nome_mun, uf)
            SELECT '999999', 'Municipio ignorado', 'NI'
            WHERE '999999' NOT IN (SELECT cod_mun FROM dim_municipio)
        """)

    print("\nMetadados de proveniencia:")
    meta, _ = procurar_apoio(Path(a.meta), list(METADADOS.values()))
    if meta != Path(a.meta):
        print(f"  (--meta {a.meta} nao tinha os CSVs; usando {meta})")
    meta_ausentes = []
    for tabela, arq in METADADOS.items():
        ok = carregar_csv(con, tabela, meta / arq)
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0] if ok else 0
        print(f"  {tabela:22s} {'OK  ' + fmt(n) + ' linhas' if ok else 'AUSENTE (' + arq + ')'}")
        if not ok:
            meta_ausentes.append(arq)

    config_gravar(con, "raiz_parquet", str(raiz))
    config_gravar(con, "dicionarios", str(dic))
    config_gravar(con, "meta", str(meta))
    config_gravar(con, "criado_em", agora())

    if faltando or meta_ausentes:
        print("\n" + "=" * 70)
        print("ATENCAO: apoio incompleto. As checagens que dependem destes")
        print("arquivos vao ser PULADAS, e um relatorio pela metade nao e")
        print("atestado de que a base esta boa.")
        for arq in faltando:
            print(f"  - {arq:24s} (dimensao)  procurado em {dic}")
        for arq in meta_ausentes:
            print(f"  - {arq:24s} (metadado)  procurado em {meta}")
        if "conversao.csv" in meta_ausentes:
            print("\n  conversao.csv e manifesto.csv sao gravados pelo")
            print("  pdet_parquet.py / pdet_download.py na raiz de dados")
            print("  (E:\\pdet), nao na pasta do projeto. Sem conversao.csv a")
            print("  checagem 'conferencia_com_manifesto' - a que compara as")
            print("  linhas do Parquet com as que a conversao diz ter escrito -")
            print("  nao roda. Aponte --meta para onde eles estao.")
        print("=" * 70)
        if not a.parcial:
            sys.exit("\nERRO: rode de novo apontando --dicionarios/--meta para "
                     "as pastas certas, ou use --parcial para aceitar o banco "
                     "incompleto de proposito.")

    print("\nInventario rapido (contagem por ano - le so o rodape dos "
          "Parquet, e rapido):")
    for base, pasta in BASES.items():
        if base not in achadas:
            continue
        print(f"\n  {base}")
        imprimir(con, f"""
            SELECT ano, count(*) AS linhas, count(DISTINCT uf) AS ufs
            FROM src_{pasta} GROUP BY ano ORDER BY ano
        """, limite=30)

    con.close()
    print(f"\nPronto. Rode agora:  python {Path(sys.argv[0]).name} checar "
          f"--banco {a.banco}")


# ===========================================================================
# checar - bateria de integridade
# ===========================================================================

CHECAGENS = [
    ("cobertura_ano_uf",
     "Linhas por ano e UF nos vinculos. Uma UF que despenca ou dispara de "
     "um ano para o outro e arquivo truncado ou duplicado, nao economia.",
     """
     SELECT ano, uf, count(*) AS linhas,
            round(100.0 * count(*) / nullif(lag(count(*))
                  OVER (PARTITION BY uf ORDER BY ano), 0) - 100, 1)
                AS variacao_pct
     FROM src_rais_vinculos GROUP BY ano, uf ORDER BY uf, ano
     """),

    ("particao_com_varias_origens",
     "Cada particao ano/uf deveria receber dados de UMA unidade de conversao "
     "(um arquivo do FTP). Duas ou mais = provavel duplicacao de linhas.",
     """
     WITH f AS (
       SELECT ano, uf, filename,
              -- so o nome do arquivo, e o token ancorado: aplicado ao
              -- caminho inteiro o padrao casava com 'ue' de /dados_ue_/ e
              -- com 'uf' de /uf=AC/, devolvia lixo igual para todo mundo e
              -- a checagem passava sempre - falso negativo silencioso.
              regexp_extract(regexp_extract(filename, '[^/\\\\]+$'),
                             '^u([0-9a-f]{10})_', 1) AS token
       FROM arq_rais_vinculos GROUP BY ALL)
     SELECT ano, uf, count(DISTINCT token) AS origens,
            count(*) AS arquivos_parquet,
            count(*) FILTER (WHERE token = '') AS sem_token,
            string_agg(DISTINCT token, ', ') AS tokens
     FROM f GROUP BY ano, uf
     HAVING count(DISTINCT token) > 1 OR count(*) FILTER (WHERE token = '') > 0
     ORDER BY ano, uf
     """),

    ("anomalia_ano_uf",
     "Recorte curto da checagem 1, so com o que destoa: contagem exatamente "
     "igual em UFs diferentes no mesmo ano (dois estados nao empatam na "
     "unidade - e o mesmo arquivo lido duas vezes) e variacao anual acima "
     "de 25% (queda = truncamento, salto = duplicacao). A regra dos 25% so "
     "vale para particao com 50 mil linhas ou mais: a pseudo-UF NI (o "
     "arquivo RAIS_VINC_PUB_NI, de vinculo sem municipio) tem algumas "
     "centenas ou milhares de linhas e varia centenas por cento por ano "
     "sem que nada esteja errado - ela sai listada a parte, como "
     "'particao minuscula', para nao sumir do relatorio nem afogar o resto.",
     """
     WITH c AS (SELECT ano, uf, count(*) AS linhas
                FROM src_rais_vinculos GROUP BY 1, 2),
     gemeas AS (SELECT ano, linhas, string_agg(uf, '+' ORDER BY uf) AS ufs
                FROM c GROUP BY 1, 2 HAVING count(*) > 1),
     serie AS (SELECT ano, uf, linhas,
                      lag(linhas) OVER (PARTITION BY uf ORDER BY ano) AS ant
               FROM c)
     SELECT 'contagem identica entre UFs' AS tipo, ano, ufs AS uf,
            linhas, CAST(NULL AS DOUBLE) AS variacao_pct
     FROM gemeas
     UNION ALL
     SELECT 'variacao anual acima de 25%', ano, uf, linhas,
            round(100.0 * linhas / ant - 100, 1)
     FROM serie
     WHERE ant IS NOT NULL AND linhas >= 50000 AND ant >= 50000
       AND abs(100.0 * linhas / ant - 100) > 25
     UNION ALL
     SELECT 'particao minuscula (regra dos 25% nao se aplica)', ano, uf,
            linhas, round(100.0 * linhas / ant - 100, 1)
     FROM serie
     WHERE linhas < 50000 OR ant < 50000
     ORDER BY tipo, ano, uf
     """),

    ("conferencia_com_manifesto",
     "Linhas no Parquet x linhas registradas em conversao.csv. Divergencia "
     "significa arquivo movido, apagado ou convertido duas vezes.",
     """
     WITH m AS (
       SELECT CAST(ano AS INTEGER) AS ano, sum(CAST(linhas AS BIGINT)) AS m_linhas
       FROM meta_conversao WHERE status = 'ok' AND base = 'RAIS_VINCULOS'
       GROUP BY 1),
     b AS (SELECT ano, count(*) AS b_linhas FROM src_rais_vinculos GROUP BY 1)
     SELECT coalesce(b.ano, m.ano) AS ano, m.m_linhas, b.b_linhas,
            coalesce(b.b_linhas, 0) - coalesce(m.m_linhas, 0) AS diferenca
     FROM b FULL JOIN m USING (ano)
     WHERE coalesce(b.b_linhas, 0) <> coalesce(m.m_linhas, 0) ORDER BY 1
     """),

    ("estoque_brasil",
     "Vinculos ativos em 31/12, Brasil. E a serie que todo relatorio abre. "
     "Compare com a RAIS publicada: a ordem de grandeza e de 44 a 55 milhoes "
     "no periodo. Se estiver muito acima, ha duplicacao.",
     """
     SELECT ano,
            count(*) AS vinculos_declarados,
            count(*) FILTER (WHERE vinculo_ativo_3112) AS ativos_3112,
            round(100.0 * count(*) FILTER (WHERE vinculo_ativo_3112)
                  / count(*), 1) AS pct_ativos
     FROM vinculos GROUP BY ano ORDER BY ano
     """),

    ("municipio_sem_ibge",
     "Codigos de municipio que nao existem na tabela do IBGE. Um punhado e "
     "normal (municipios extintos, codigo ignorado); muitos indicam coluna "
     "trocada de posicao.",
     """
     SELECT v.ano, v.cod_mun, count(*) AS linhas
     FROM vinculos v LEFT JOIN dim_municipio m USING (cod_mun)
     WHERE m.cod_mun IS NULL
     GROUP BY 1, 2 ORDER BY linhas DESC
     """),

    ("uf_incoerente",
     "A particao uf e derivada dos 2 primeiros digitos do municipio. Se nao "
     "bate com a UF do IBGE, a derivacao errou.",
     """
     SELECT v.ano, v.uf AS uf_particao, m.uf AS uf_ibge, count(*) AS linhas
     FROM vinculos v JOIN dim_municipio m USING (cod_mun)
     WHERE v.uf <> m.uf GROUP BY 1, 2, 3 ORDER BY linhas DESC
     """),

    ("cnae_sem_dicionario",
     "Classes CNAE 2.0 sem correspondencia. Espera-se pouca coisa: codigos "
     "zerados e a CNAE 1.0 residual dos anos antigos.",
     """
     SELECT v.ano, lpad(v.cnae20_classe, 5, '0') AS cnae, count(*) AS linhas
     FROM vinculos v
     LEFT JOIN dim_cnae_classe c ON c.cnae_classe = lpad(v.cnae20_classe, 5, '0')
     WHERE v.cnae20_classe IS NOT NULL AND c.cnae_classe IS NULL
     GROUP BY 1, 2 ORDER BY linhas DESC
     """),

    ("nulos_nas_colunas_chave",
     "Percentual de nulos nas colunas que os relatorios usam. Um salto de "
     "0% para 100% num ano e coluna que mudou de posicao no layout.",
     """
     SELECT ano,
            round(100.0 * count(*) FILTER (WHERE municipio IS NULL) / count(*), 1) AS mun,
            round(100.0 * count(*) FILTER (WHERE sexo IS NULL) / count(*), 1) AS sexo,
            round(100.0 * count(*) FILTER (WHERE grau_instrucao IS NULL) / count(*), 1) AS instr,
            round(100.0 * count(*) FILTER (WHERE cnae20_classe IS NULL) / count(*), 1) AS cnae,
            round(100.0 * count(*) FILTER (WHERE remun_dez_nom IS NULL) / count(*), 1) AS remun_dez,
            round(100.0 * count(*) FILTER (WHERE vinculo_ativo_3112 IS NULL) / count(*), 1) AS ativo,
            round(100.0 * count(*) FILTER (WHERE cbo_2002 IS NULL) / count(*), 1) AS cbo
     FROM vinculos GROUP BY ano ORDER BY ano
     """),

    ("remuneracao_suspeita",
     "Remuneracao de dezembro fora de faixa plausivel entre os ativos. "
     "Negativos ou valores estratosfericos denunciam decimal mal lido.",
     """
     SELECT ano,
            count(*) FILTER (WHERE remun_dez_nom < 0) AS negativos,
            count(*) FILTER (WHERE remun_dez_nom = 0) AS zerados,
            count(*) FILTER (WHERE remun_dez_nom > 1000000) AS acima_1_milhao,
            round(median(remun_dez_nom), 2) AS mediana,
            round(max(remun_dez_nom), 2) AS maximo
     FROM vinculos WHERE vinculo_ativo_3112 GROUP BY ano ORDER BY ano
     """),

    ("coerencia_com_salario_minimo",
     "A mediana da remuneracao de dezembro dividida pelo salario minimo do "
     "ano. A faixa esperada DEPENDE DO RECORTE carregado: com o Brasil "
     "inteiro fica entre 1,8 e 2,0 (medido: 1,81 a 1,99 de 2010 a 2025); so "
     "com o Nordeste, entre 1,3 e 1,6. "
     "Confira qual recorte esta na base antes de gritar - fora da faixa do "
     "proprio recorte, ha erro de escala. O filtro remun > 0 nao e detalhe: "
     "ate 2022 quem nao recebeu em dezembro entra como 0 e a partir de 2023 "
     "como NULL, entao sem ele a serie salta sozinha na virada 2022/2023.",
     """
     SELECT v.ano, round(median(v.remun_dez_nom), 2) AS mediana_nom,
            CAST(a.salario_minimo_dez AS DOUBLE) AS sal_min,
            round(median(v.remun_dez_nom) / CAST(a.salario_minimo_dez AS DOUBLE), 2)
                AS mediana_em_sm
     FROM vinculos v JOIN dim_ano a ON CAST(a.ano AS INTEGER) = v.ano
     WHERE v.vinculo_ativo_3112 AND v.remun_dez_nom > 0
     GROUP BY v.ano, a.salario_minimo_dez ORDER BY v.ano
     """),

    ("colunas_por_esquema",
     "Quais colunas existem em quais anos. E o mapa do que da para comparar "
     "na serie historica e do que nao da.",
     """
     SELECT nome_canonico,
            string_agg(DISTINCT ano_de || '-' || ano_ate, ', '
                       ORDER BY ano_de || '-' || ano_ate) AS esquemas
     FROM meta_colunas WHERE base = 'RAIS_VINCULOS'
     GROUP BY 1 HAVING count(*) < (SELECT count(DISTINCT ano_de || ano_ate)
                                   FROM meta_colunas WHERE base = 'RAIS_VINCULOS')
     ORDER BY 1
     """),

    ("estabelecimentos_por_ano",
     "Estabelecimentos declarantes por ano. Serie estavel na casa dos 8 "
     "milhoes ate 2022.",
     """
     SELECT ano, count(*) AS estabelecimentos,
            count(*) FILTER (WHERE ind_rais_negativa = 1) AS rais_negativa,
            sum(qtd_vinculos_ativos) AS soma_vinculos_ativos
     FROM estabelecimentos GROUP BY ano ORDER BY ano
     """),

    ("conciliacao_estab_vinculos",
     "As duas bases tem que fechar: o que os estabelecimentos declaram como "
     "vinculo ativo em 31/12, mais os vinculos marcados como abandonados, da "
     "exatamente a contagem de ativos da base de vinculos. A coluna 'sobra' "
     "tem que ser ZERO em todo ano. Se nao for, ou falta unidade numa das "
     "duas arvores, ou algum marcador de ausente esta comendo grandeza -- foi "
     "o que aconteceu em 2023-2025, quando o '99' da lista de nulos anulava a "
     "contagem dos estabelecimentos com 99 empregados.",
     """
     WITH e AS (SELECT ano, sum(qtd_vinculos_ativos) AS declarado
                FROM estabelecimentos GROUP BY ano),
          v AS (SELECT ano,
                       count(*) FILTER (WHERE vinculo_ativo_3112) AS ativos,
                       count(*) FILTER (WHERE vinculo_ativo_3112
                                          AND ind_vinculo_abandonado = 1)
                           AS abandonados
                FROM vinculos GROUP BY ano)
     SELECT e.ano, v.ativos, e.declarado,
            e.declarado - v.ativos                       AS diferenca,
            coalesce(v.abandonados, 0)                   AS abandonados,
            e.declarado + coalesce(v.abandonados, 0) - v.ativos AS sobra
     FROM e JOIN v USING (ano) ORDER BY e.ano
     """),
]


# Tabelas de apoio que cada checagem exige. Sem isso o 'checar' antigo
# gravava um "FALHOU: table does not exist" no meio do relatorio, do mesmo
# tamanho de um erro de verdade, e o resumo final nao existia - dava para
# ler um relatorio com 5 de 12 checagens mortas como se fosse aprovacao.
DEPENDE = {
    "conferencia_com_manifesto": ["meta_conversao"],
    "municipio_sem_ibge": ["dim_municipio"],
    "uf_incoerente": ["dim_municipio"],
    "cnae_sem_dicionario": ["dim_cnae_classe"],
    "coerencia_com_salario_minimo": ["dim_ano"],
    "colunas_por_esquema": ["meta_colunas"],
    "estabelecimentos_por_ano": ["estabelecimentos"],
    "conciliacao_estab_vinculos": ["estabelecimentos", "vinculos"],
    "cobertura_ano_uf": ["src_rais_vinculos"],
    "anomalia_ano_uf": ["src_rais_vinculos"],
    "particao_com_varias_origens": ["arq_rais_vinculos"],
    "estoque_brasil": ["vinculos"],
    "nulos_nas_colunas_chave": ["vinculos"],
    "remuneracao_suspeita": ["vinculos"],
}


def cmd_checar(a) -> None:
    con = abrir(a.banco, a.memoria, a.threads, a.tmp, leitura=False)
    saida = Path(a.saida) if a.saida else Path("estado/checagem_banco.md")
    linhas = [f"# Checagem do banco PDET", "",
              f"- Banco: `{a.banco}`",
              f"- Parquet: `{config_ler(con, 'raiz_parquet', '?')}`",
              f"- Gerado em: {agora()}", ""]

    escolhidas = [c for c in CHECAGENS
                  if not a.checagem or c[0] in a.checagem]
    if a.listar:
        for nome, desc, _ in CHECAGENS:
            print(f"{nome}\n    {desc}\n")
        return

    limite = a.limite if a.limite and a.limite > 0 else None
    veredito = {}          # nome -> "ok" | "achou" | "pulada" | "falhou"

    for i, (nome, desc, sql) in enumerate(escolhidas, 1):
        print(f"\n[{i}/{len(escolhidas)}] {nome}")
        print(f"  {desc}")
        t0 = time.time()
        linhas += [f"## {i}. {nome}", "", desc, ""]

        ausentes = [t for t in DEPENDE.get(nome, [])
                    if not objeto_existe(con, t)]
        if ausentes:
            msg = ("PULADA: falta " + ", ".join(f"`{t}`" for t in ausentes)
                   + ". Esta checagem NAO rodou - rode `criar` de novo "
                     "apontando --parquet para a raiz certa e "
                     "--dicionarios/--meta para as pastas com os CSVs "
                     "de apoio.")
            print(f"  {msg}")
            linhas += [f"> {msg}", ""]
            veredito[nome] = "pulada"
            continue

        try:
            rel = con.sql(sql)
            cols = rel.columns
            dados = rel.fetchall() if limite is None else rel.fetchmany(limite + 1)
            cortado = limite is not None and len(dados) > limite
            if cortado:
                dados = dados[:limite]
        except Exception as e:                               # noqa: BLE001
            msg = f"FALHOU: {type(e).__name__}: {str(e)[:300]}"
            print(f"  {msg}")
            linhas += [f"> {msg}", ""]
            veredito[nome] = "falhou"
            continue
        dt = time.time() - t0
        if not dados:
            print(f"  sem ocorrencias ({dt:.1f}s)")
            linhas += ["Sem ocorrencias.", ""]
            veredito[nome] = "ok"
            continue
        print(f"  {len(dados)} linha(s) em {dt:.1f}s")
        veredito[nome] = "achou"
        linhas.append("| " + " | ".join(cols) + " |")
        linhas.append("|" + "|".join("---" for _ in cols) + "|")
        for d in dados:
            linhas.append("| " + " | ".join(
                "" if v is None else str(v) for v in d) + " |")
        if cortado:
            linhas.append(f"| ... | CORTADO em {limite} linhas - use "
                          f"`--limite 0` para o relatorio completo |"
                          + " |" * (len(cols) - 2))
        linhas.append("")
        if a.mostrar:
            imprimir(con, sql, limite=25 if limite is None else min(limite, 25))

    # resumo no topo: quantas checagens de fato rodaram
    mortas = [n for n, v in veredito.items() if v in ("pulada", "falhou")]
    rodaram = len(veredito) - len(mortas)
    resumo = ["## Resumo", "",
              f"- Checagens executadas: **{rodaram} de {len(escolhidas)}**"]
    if mortas:
        resumo += [f"- **Nao executadas: {len(mortas)}** - "
                   + ", ".join(f"`{n}` ({veredito[n]})" for n in mortas),
                   "",
                   "> Enquanto essas nao rodarem, este relatorio nao autoriza "
                   "`agregar`: as checagens que faltam sao justamente as que "
                   "cruzam o Parquet com a proveniencia e com as tabelas do "
                   "IBGE."]
    else:
        resumo.append("- Nenhuma checagem foi pulada.")
    resumo.append("")
    linhas[6:6] = resumo

    saida.write_text("\n".join(linhas), encoding="utf-8")
    con.close()
    print(f"\n{rodaram} de {len(escolhidas)} checagens executadas."
          + (f" NAO executadas: {', '.join(mortas)}" if mortas else ""))
    print(f"Relatorio: {saida.resolve()}")


# ===========================================================================
# codigos - o que a base tem x o que o dicionario rotula
# ===========================================================================

CATEGORICAS = [
    "sexo", "raca_cor", "grau_instrucao", "faixa_etaria", "faixa_hora_contrat",
    "faixa_tempo_emprego", "faixa_remun_media_sm", "faixa_remun_dez_sm",
    "tamanho_estab", "tipo_vinculo", "tipo_admissao", "motivo_desligamento",
    "ibge_subsetor", "nacionalidade", "tipo_defic", "ind_portador_defic",
    "ind_simples", "tipo_estab", "ind_trab_parcial", "ind_trab_intermitente",
    "causa_afastamento_1", "categoria_trabalhador", "ind_vinculo_abandonado",
]


def cmd_codigos(a) -> None:
    con = abrir(a.banco, a.memoria, a.threads, a.tmp)
    filtro = f"AND ano = {int(a.ano)}" if a.ano else ""
    # NULL fica de fora de proposito: coluna que nao existe naquele layout
    # nao e codigo sem rotulo, e coluna ausente.
    partes = []
    for col in CATEGORICAS:
        partes.append(f"""
            SELECT '{col}' AS variavel, CAST({col} AS VARCHAR) AS codigo,
                   count(*) AS linhas, min(ano) AS primeiro_ano,
                   max(ano) AS ultimo_ano
            FROM vinculos WHERE {col} IS NOT NULL {filtro} GROUP BY 2""")
    # A varredura e cara (le uma coluna categorica de cada vez sobre a base
    # inteira). Materializar UMA vez e reusar: a versao anterior repetia o
    # mesmo SQL tres vezes -- no COPY, na contagem e no top 30 -- e triplicava
    # um trabalho que ja passa de uma hora com a base nacional no USB.
    print("Varrendo os codigos observados (le muitas colunas; leva alguns "
          "minutos)...\n")
    con.execute("CREATE OR REPLACE TEMP TABLE obs_codigos AS "
                + " UNION ALL ".join(partes))

    # O join carrega a janela de anos porque ha codigo que muda de significado:
    # 'faixa_remun_media_sm' vale 0..11 ate 2022 e 1..12 de 2023 em diante, com
    # o mesmo numero querendo dizer faixas diferentes dos dois lados.
    sql = """
        SELECT o.variavel, o.codigo, o.linhas, o.primeiro_ano, o.ultimo_ano,
               coalesce(d.rotulo, '>>> SEM ROTULO <<<') AS rotulo,
               d.ano_de, d.ano_ate, d.confianca
        FROM obs_codigos o
        LEFT JOIN dim_codigos d
               ON d.variavel = o.variavel AND d.codigo = o.codigo
              AND CAST(d.ano_ate AS INTEGER) >= o.primeiro_ano
              AND CAST(d.ano_de  AS INTEGER) <= o.ultimo_ano
        ORDER BY o.variavel, try_cast(o.codigo AS INTEGER), o.codigo,
                 try_cast(d.ano_de AS INTEGER)
    """
    saida = Path(a.saida) if a.saida else Path("codigos_observados.csv")
    con.execute(f"COPY ({sql}) TO '{p(saida)}' (HEADER, DELIMITER ',')")
    n_sem = con.execute(f"""
        SELECT count(*) FROM ({sql}) WHERE rotulo = '>>> SEM ROTULO <<<'
    """).fetchone()[0]
    print(f"Arquivo: {saida.resolve()}")
    print(f"{n_sem} combinacao(oes) variavel/codigo sem rotulo em "
          f"dim_codigos.csv.")
    if n_sem:
        print("\nAs 30 mais frequentes sem rotulo:")
        imprimir(con, f"""
            SELECT * FROM ({sql}) WHERE rotulo = '>>> SEM ROTULO <<<'
            ORDER BY linhas DESC LIMIT 30""", limite=30)
        print("\nComplete dim_codigos.csv pelo layout oficial do MTE e rode "
              "'criar' de novo.")
    con.close()


# ===========================================================================
# agregar - os cubos
# ===========================================================================

MEDIDAS_VINC = """
    count(*)                                                    AS vinculos,
    count(*) FILTER (WHERE vinculo_ativo_3112)                  AS ativos,
    count(*) FILTER (WHERE mes_admissao BETWEEN 1 AND 12)       AS admitidos,
    count(*) FILTER (WHERE mes_desligamento BETWEEN 1 AND 12)   AS desligados,
    count(*) FILTER (WHERE vinculo_ativo_3112 AND sexo = 2)     AS ativos_fem,
    count(*) FILTER (WHERE vinculo_ativo_3112 AND setor_publico) AS ativos_publico,
    sum(remun_dez_nom) FILTER (WHERE vinculo_ativo_3112)        AS massa_dez,
    -- as duas populacoes, de proposito: 'ativos' conta todo mundo, e
    -- 'ativos_com_remun' so quem recebeu em dezembro. Ate 2022 quem nao
    -- recebeu vem com 0 literal e de 2023 em diante vem NULL -- sem separar
    -- os dois, a media troca de denominador no meio da serie e ninguem ve.
    count(*) FILTER (WHERE vinculo_ativo_3112
                       AND remun_dez_nom > 0)                   AS ativos_com_remun,
    avg(remun_dez_nom) FILTER (WHERE vinculo_ativo_3112
                                 AND remun_dez_nom > 0)         AS remun_dez_media,
    avg(remun_media_nom) FILTER (WHERE vinculo_ativo_3112)      AS remun_media_ano,
    avg(qtd_hora_contr) FILTER (WHERE vinculo_ativo_3112)       AS horas_media,
    avg(idade) FILTER (WHERE vinculo_ativo_3112)                AS idade_media,
    avg(tempo_emprego) FILTER (WHERE vinculo_ativo_3112)        AS tempo_emprego_medio
"""

CUBOS = {}


def _sql_cubo_mun(filtro: str) -> str:
    return f"""
    CREATE OR REPLACE TEMP TABLE _cubo_mun AS
    SELECT ano, uf, cod_mun,
           coalesce(c.cnae_secao, '?')            AS cnae_secao,
           v.tamanho_estab,
           GROUPING(coalesce(c.cnae_secao, '?'))  AS g_secao,
           GROUPING(v.tamanho_estab)              AS g_tam,
           {MEDIDAS_VINC},
           approx_quantile(remun_dez_nom, 0.5)
               FILTER (WHERE vinculo_ativo_3112 AND remun_dez_nom > 0)
               AS remun_dez_p50
    FROM vinculos v
    LEFT JOIN dim_cnae_classe c
           ON c.cnae_classe = lpad(v.cnae20_classe, 5, '0')
    {filtro}
    GROUP BY GROUPING SETS (
        (ano, uf, cod_mun, coalesce(c.cnae_secao, '?'), v.tamanho_estab),
        (ano, uf, cod_mun)
    )
    """


def cmd_agregar(a) -> None:
    con = abrir(a.banco, a.memoria, a.threads, a.tmp)
    anos = [int(x) for x in a.ano] if a.ano else []
    filtro_v = f"WHERE v.ano IN ({', '.join(map(str, anos))})" if anos else ""
    filtro_e = f"WHERE e.ano IN ({', '.join(map(str, anos))})" if anos else ""
    ufs = [u.upper() for u in a.uf_detalhe]
    lista_ufs = ", ".join(f"'{u}'" for u in ufs) if ufs else "''"
    if anos:
        print(f"Reconstruindo apenas os anos: {', '.join(map(str, anos))}")
    else:
        print("Reconstruindo TODOS os anos. Use --ano para atualizar so um.")
    if ufs:
        print(f"Detalhe municipal extra para: {', '.join(ufs)}")
    t_geral = time.time()

    def limpar(tabela: str) -> None:
        """Apaga so o que sera reescrito. Sem --ano, a tabela e refeita."""
        if tabela_existe(con, tabela) and anos:
            con.execute(f"DELETE FROM {tabela} WHERE ano IN "
                        f"({', '.join(map(str, anos))})")

    def gravar(tabela: str, sql: str) -> None:
        t0 = time.time()
        print(f"\n  {tabela} ...", end="", flush=True)
        if tabela_existe(con, tabela) and anos:
            limpar(tabela)
            con.execute(f"INSERT INTO {tabela} {sql}")
        else:
            con.execute(f"CREATE OR REPLACE TABLE {tabela} AS {sql}")
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        print(f" {fmt(n)} linhas ({time.time() - t0:.0f}s)")

    # -- passada 1: municipio x secao x tamanho, com rollup no municipio ----
    print("\n[1/4] varredura principal dos vinculos "
          "(municipio x secao x tamanho)")
    t0 = time.time()
    con.execute(_sql_cubo_mun(filtro_v))
    print(f"      varredura concluida em {(time.time() - t0) / 60:.1f} min")

    gravar("fato_vinc_mun", """
        SELECT ano, uf, cod_mun, vinculos, ativos, admitidos, desligados,
               ativos_fem, ativos_publico, massa_dez, ativos_com_remun,
               remun_dez_media,
               remun_dez_p50, remun_media_ano, horas_media, idade_media,
               tempo_emprego_medio
        FROM _cubo_mun WHERE g_secao = 1 AND g_tam = 1
    """)
    # o grao fino carrega tambem tamanho_estab: aqui ele e somado fora
    gravar("fato_vinc_mun_secao", """
        SELECT ano, uf, cod_mun, cnae_secao,
               sum(vinculos) AS vinculos, sum(ativos) AS ativos,
               sum(admitidos) AS admitidos, sum(desligados) AS desligados,
               sum(ativos_fem) AS ativos_fem,
               sum(ativos_publico) AS ativos_publico,
               sum(massa_dez) AS massa_dez,
               sum(ativos_com_remun) AS ativos_com_remun,
               sum(massa_dez) / nullif(sum(ativos_com_remun), 0)
                   AS remun_dez_media
        FROM _cubo_mun WHERE g_secao = 0
        GROUP BY ano, uf, cod_mun, cnae_secao
    """)
    gravar("fato_vinc_tamanho", """
        SELECT ano, uf, tamanho_estab,
               sum(vinculos) AS vinculos, sum(ativos) AS ativos,
               sum(massa_dez) AS massa_dez,
               sum(ativos_com_remun) AS ativos_com_remun,
               sum(massa_dez) / nullif(sum(ativos_com_remun), 0)
                   AS remun_dez_media
        FROM _cubo_mun WHERE g_tam = 0
        GROUP BY ano, uf, tamanho_estab
    """)
    con.execute("DROP TABLE IF EXISTS _cubo_mun")

    # -- passada 2: perfil demografico ------------------------------------
    print("\n[2/4] perfil demografico (UF; municipio nas UFs de detalhe)")
    gravar("fato_vinc_perfil", f"""
        SELECT ano, uf,
               CASE WHEN uf IN ({lista_ufs}) THEN cod_mun END AS cod_mun,
               sexo, raca_cor, grau_instrucao, faixa_etaria,
               count(*) AS vinculos,
               count(*) FILTER (WHERE vinculo_ativo_3112) AS ativos,
               count(*) FILTER (WHERE mes_admissao BETWEEN 1 AND 12) AS admitidos,
               count(*) FILTER (WHERE mes_desligamento BETWEEN 1 AND 12) AS desligados,
               sum(remun_dez_nom) FILTER (WHERE vinculo_ativo_3112) AS massa_dez,
               count(*) FILTER (WHERE vinculo_ativo_3112
                                  AND remun_dez_nom > 0) AS ativos_com_remun,
               avg(remun_dez_nom) FILTER (WHERE vinculo_ativo_3112
                                            AND remun_dez_nom > 0)
                   AS remun_dez_media
        FROM vinculos v {filtro_v}
        GROUP BY ALL
    """)

    # -- passada 3: fluxo mensal ------------------------------------------
    print("\n[3/4] fluxo mensal de admissoes e desligamentos")
    gravar("fato_vinc_fluxo_mes", f"""
        SELECT ano, uf, cod_mun, mes,
               sum(adm)::BIGINT AS admissoes,
               sum(desl)::BIGINT AS desligamentos,
               sum(massa_adm) AS massa_admissao
        FROM (
            SELECT ano, uf, cod_mun,
                   unnest([mes_admissao, mes_desligamento]) AS mes,
                   unnest([1, 0]) AS adm,
                   unnest([0, 1]) AS desl,
                   unnest([remun_media_nom, NULL]) AS massa_adm
            FROM vinculos v
            {filtro_v or 'WHERE true'}
              AND (mes_admissao BETWEEN 1 AND 12
                   OR mes_desligamento BETWEEN 1 AND 12)
        )
        WHERE mes BETWEEN 1 AND 12
        GROUP BY ALL
    """)

    # -- passada 4: ocupacao (so UFs de detalhe) --------------------------
    if ufs:
        print("\n[4/4] ocupacoes (CBO) nas UFs de detalhe")
        gravar("fato_vinc_ocupacao", f"""
            SELECT ano, uf, cod_mun, cbo_2002, cbo_grande_grupo,
                   count(*) FILTER (WHERE vinculo_ativo_3112) AS ativos,
                   count(*) FILTER (WHERE vinculo_ativo_3112
                                      AND remun_dez_nom > 0) AS ativos_com_remun,
                   avg(remun_dez_nom) FILTER (WHERE vinculo_ativo_3112
                                                AND remun_dez_nom > 0)
                       AS remun_dez_media,
                   count(*) FILTER (WHERE mes_admissao BETWEEN 1 AND 12)
                       AS admitidos
            FROM vinculos v
            WHERE uf IN ({lista_ufs})
            {('AND ano IN (' + ', '.join(map(str, anos)) + ')') if anos else ''}
            GROUP BY ALL
        """)
    else:
        print("\n[4/4] ocupacoes: pulado (informe --uf-detalhe PI)")

    # -- estabelecimentos --------------------------------------------------
    if tabela_existe(con, "meta_conversao") or True:
        print("\n[+] estabelecimentos")
        gravar("fato_estab_mun", f"""
            SELECT e.ano, e.uf, e.cod_mun,
                   coalesce(c.cnae_secao, '?') AS cnae_secao,
                   e.tamanho_estab,
                   count(*) AS estabelecimentos,
                   count(*) FILTER (WHERE e.ind_rais_negativa = 1) AS rais_negativa,
                   sum(e.qtd_vinculos_ativos) AS vinculos_ativos,
                   sum(e.qtd_vinculos_clt) AS vinculos_clt,
                   sum(e.qtd_vinculos_estat) AS vinculos_estat
            FROM estabelecimentos e
            LEFT JOIN dim_cnae_classe c
                   ON c.cnae_classe = lpad(e.cnae20_classe, 5, '0')
            {filtro_e}
            GROUP BY ALL
        """)

    criar_views_de_leitura(con)
    config_gravar(con, "agregado_em", agora())
    con.execute("CHECKPOINT")
    con.close()
    print(f"\nCubos prontos em {(time.time() - t_geral) / 60:.1f} min.")


def criar_views_de_leitura(con) -> None:
    """Views com rotulo e valor deflacionado - o que as consultas usam."""
    con.execute("""
        CREATE OR REPLACE VIEW v_municipio_ano AS
        SELECT f.ano, f.uf, m.uf_nome, m.regiao, f.cod_mun, m.nome_mun,
               m.reg_intermediaria, m.reg_imediata,
               f.vinculos, f.ativos, f.admitidos, f.desligados,
               f.admitidos - f.desligados                       AS saldo,
               f.ativos_fem,
               round(100.0 * f.ativos_fem / nullif(f.ativos, 0), 1) AS pct_fem,
               f.ativos_publico,
               round(100.0 * f.ativos_publico / nullif(f.ativos, 0), 1) AS pct_publico,
               f.massa_dez, f.ativos_com_remun,
               f.remun_dez_media, f.remun_dez_p50,
               round(f.remun_dez_media * CAST(a.deflator AS DOUBLE), 2)
                   AS remun_dez_media_real,
               round(f.remun_dez_media / CAST(a.salario_minimo_dez AS DOUBLE), 2)
                   AS remun_dez_media_sm,
               a.ano_base_deflator,
               f.horas_media, f.idade_media, f.tempo_emprego_medio
        FROM fato_vinc_mun f
        LEFT JOIN dim_municipio m USING (cod_mun)
        LEFT JOIN dim_ano a ON CAST(a.ano AS INTEGER) = f.ano
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v_uf_ano AS
        SELECT f.ano, f.uf, any_value(u.uf_nome) AS uf_nome,
               any_value(u.regiao) AS regiao,
               sum(f.vinculos) AS vinculos, sum(f.ativos) AS ativos,
               sum(f.admitidos) AS admitidos, sum(f.desligados) AS desligados,
               sum(f.admitidos) - sum(f.desligados) AS saldo,
               sum(f.ativos_fem) AS ativos_fem,
               sum(f.ativos_publico) AS ativos_publico,
               sum(f.massa_dez) AS massa_dez,
               sum(f.ativos_com_remun) AS ativos_com_remun,
               sum(f.massa_dez) / nullif(sum(f.ativos_com_remun), 0)
                   AS remun_dez_media,
               round(sum(f.massa_dez) / nullif(sum(f.ativos_com_remun), 0)
                     * any_value(CAST(a.deflator AS DOUBLE)), 2)
                   AS remun_dez_media_real
        FROM fato_vinc_mun f
        LEFT JOIN dim_uf u USING (uf)
        LEFT JOIN dim_ano a ON CAST(a.ano AS INTEGER) = f.ano
        GROUP BY f.ano, f.uf
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v_setor_ano AS
        SELECT f.ano, f.uf, f.cod_mun, m.nome_mun, f.cnae_secao,
               any_value(c.desc_secao) AS desc_secao,
               sum(f.ativos) AS ativos, sum(f.admitidos) AS admitidos,
               sum(f.desligados) AS desligados,
               sum(f.admitidos) - sum(f.desligados) AS saldo,
               sum(f.massa_dez) AS massa_dez,
               sum(f.ativos_com_remun) AS ativos_com_remun,
               sum(f.massa_dez) / nullif(sum(f.ativos_com_remun), 0)
                   AS remun_dez_media
        FROM fato_vinc_mun_secao f
        LEFT JOIN dim_municipio m USING (cod_mun)
        LEFT JOIN (SELECT DISTINCT cnae_secao, desc_secao FROM dim_cnae_classe) c
               USING (cnae_secao)
        GROUP BY ALL
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v_perfil_ano AS
        SELECT f.ano, f.uf, f.cod_mun, m.nome_mun,
               f.sexo,           s.rotulo AS sexo_rot,
               f.raca_cor,       r.rotulo AS raca_rot,
               f.grau_instrucao, g.rotulo AS instrucao_rot,
               f.faixa_etaria,   e.rotulo AS faixa_etaria_rot,
               f.vinculos, f.ativos, f.admitidos, f.desligados,
               f.massa_dez, f.ativos_com_remun, f.remun_dez_media
        FROM fato_vinc_perfil f
        LEFT JOIN dim_municipio m USING (cod_mun)
        LEFT JOIN dim_codigos s ON s.variavel = 'sexo'
                               AND s.codigo = CAST(f.sexo AS VARCHAR)
        LEFT JOIN dim_codigos r ON r.variavel = 'raca_cor'
                               AND r.codigo = CAST(f.raca_cor AS VARCHAR)
        LEFT JOIN dim_codigos g ON g.variavel = 'grau_instrucao'
                               AND g.codigo = CAST(f.grau_instrucao AS VARCHAR)
        LEFT JOIN dim_codigos e ON e.variavel = 'faixa_etaria'
                               AND e.codigo = CAST(f.faixa_etaria AS VARCHAR)
    """)


# ===========================================================================
# consulta - roda o que esta em consultas.sql
# ===========================================================================

RE_NOME = re.compile(r"^--\s*@nome:\s*(\S+)\s*$", re.M)


def ler_consultas(arquivo: Path) -> dict:
    if not arquivo.exists():
        return {}
    texto = arquivo.read_text(encoding="utf-8")
    blocos, atual, nome, desc = {}, [], None, ""
    for linha in texto.splitlines():
        m = RE_NOME.match(linha)
        if m:
            if nome:
                blocos[nome] = ("\n".join(atual).strip().rstrip(";"), desc)
            nome, atual, desc = m.group(1), [], ""
            continue
        if nome and linha.startswith("-- @desc:"):
            desc = linha.split(":", 1)[1].strip()
            continue
        if nome:
            atual.append(linha)
    if nome:
        blocos[nome] = ("\n".join(atual).strip().rstrip(";"), desc)
    return blocos


def cmd_consulta(a) -> None:
    arq = Path(a.arquivo)
    blocos = ler_consultas(arq)
    if not blocos:
        sys.exit(f"ERRO: nenhuma consulta em {arq}. O arquivo usa marcadores "
                 f"'-- @nome: xxx'.")
    if a.listar or not a.nome:
        print(f"Consultas em {arq}:\n")
        for nome, (_, desc) in blocos.items():
            print(f"  {nome:28s} {desc}")
        return
    if a.nome not in blocos:
        sys.exit(f"ERRO: '{a.nome}' nao existe. Use --listar.")
    sql, desc = blocos[a.nome]
    for chave, valor in (x.split("=", 1) for x in a.param):
        sql = sql.replace(f"${{{chave}}}", valor)
    faltando = set(re.findall(r"\$\{(\w+)\}", sql))
    if faltando:
        sys.exit(f"ERRO: faltam parametros: {', '.join(sorted(faltando))}\n"
                 f"  use --param nome=valor")

    con = abrir(a.banco, a.memoria, a.threads, a.tmp, leitura=True)
    print(f"-- {a.nome}: {desc}\n")
    t0 = time.time()
    if a.csv:
        con.execute(f"COPY ({sql}) TO '{p(a.csv)}' (HEADER, DELIMITER ',')")
        n = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        print(f"{fmt(n)} linhas gravadas em {Path(a.csv).resolve()}")
    else:
        imprimir(con, sql, limite=a.limite)
    print(f"\n({time.time() - t0:.1f}s)")
    con.close()


def cmd_sql(a) -> None:
    con = abrir(a.banco, a.memoria, a.threads, a.tmp, leitura=a.somente_leitura)
    sql = a.sql
    if sql == "-":
        sql = sys.stdin.read()
    t0 = time.time()
    if a.csv:
        con.execute(f"COPY ({sql}) TO '{p(a.csv)}' (HEADER, DELIMITER ',')")
        print(f"gravado em {Path(a.csv).resolve()}")
    else:
        imprimir(con, sql, limite=a.limite)
    print(f"\n({time.time() - t0:.1f}s)")
    con.close()


# ===========================================================================
# main
# ===========================================================================

def argumentos_globais(parser, depois: bool = False) -> None:
    """--banco, --memoria, --threads, --tmp e --limite.

    Declarados duas vezes: no parser de cima e, com default SUPPRESS, em
    cada subcomando. Assim tanto '--banco X criar' quanto 'criar --banco X'
    funcionam, e quem nao passar nada depois do subcomando nao perde o que
    passou antes."""
    d = (lambda v: argparse.SUPPRESS) if depois else (lambda v: v)
    parser.add_argument("--banco", default=d("pdet.duckdb"),
                        help="arquivo .duckdb no disco INTERNO (nunca no HD "
                             "externo nem em pasta sincronizada)")
    parser.add_argument("--memoria", type=float, default=d(9.0),
                        help="GB de RAM para o DuckDB (padrao 9, de 16 GB)")
    parser.add_argument("--threads", type=int, default=d(8))
    parser.add_argument("--tmp", default=d(""),
                        help="pasta de spill no disco INTERNO")
    parser.add_argument("--limite", type=int, default=d(40),
                        help="linhas por tabela no relatorio; 0 = sem corte")


def main() -> None:
    p_ = argparse.ArgumentParser(
        description="Banco analitico DuckDB sobre o Parquet da RAIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    argumentos_globais(p_)
    # Os mesmos globais tambem depois do subcomando: 'criar --banco X' e a
    # ordem que todo mundo tenta primeiro, e um "unrecognized arguments"
    # seco nao ajuda ninguem. SUPPRESS e o que faz a versao de depois nao
    # sobrescrever com o default a versao de antes.
    globais_depois = argparse.ArgumentParser(add_help=False)
    argumentos_globais(globais_depois, depois=True)
    sub = p_.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("criar", help="views, dimensoes e metadados",
                   parents=[globais_depois])
    c.add_argument("--parquet", required=True)
    c.add_argument("--dicionarios", default="dicionarios")
    c.add_argument("--parcial", action="store_true",
                   help="aceita apoio incompleto (checagens serao puladas)")
    c.add_argument("--meta", default=".",
                   help="pasta com conversao.csv, manifesto.csv, dic_rais.csv")
    c.set_defaults(func=cmd_criar)

    c = sub.add_parser("checar", help="bateria de integridade",
                   parents=[globais_depois])
    c.add_argument("--saida", default="")
    c.add_argument("--checagem", action="append", default=[])
    c.add_argument("--listar", action="store_true")
    c.add_argument("--mostrar", action="store_true",
                   help="tambem imprime as tabelas na tela")
    c.set_defaults(func=cmd_checar)

    c = sub.add_parser("codigos", help="codigos observados x rotulados",
                   parents=[globais_depois])
    c.add_argument("--saida", default="")
    c.add_argument("--ano", default="")
    c.set_defaults(func=cmd_codigos)

    c = sub.add_parser("agregar", help="materializa os cubos",
                   parents=[globais_depois])
    c.add_argument("--ano", action="append", default=[],
                   help="so estes anos (repetivel). Sem isso, refaz tudo.")
    c.add_argument("--uf-detalhe", action="append", default=[],
                   help="UFs com detalhe municipal extra (ex.: --uf-detalhe PI)")
    c.set_defaults(func=cmd_agregar)

    c = sub.add_parser("consulta", help="roda consultas nomeadas",
                   parents=[globais_depois])
    c.add_argument("--arquivo", default="sql/consultas.sql")
    c.add_argument("--nome", default="")
    c.add_argument("--param", action="append", default=[],
                   help="substitui ${nome} na consulta: --param uf=PI")
    c.add_argument("--csv", default="")
    c.add_argument("--listar", action="store_true")
    c.set_defaults(func=cmd_consulta)

    c = sub.add_parser("sql", help="roda um SQL avulso",
                   parents=[globais_depois])
    c.add_argument("sql", help="o SQL, ou '-' para ler da entrada padrao")
    c.add_argument("--csv", default="")
    c.add_argument("--somente-leitura", action="store_true")
    c.set_defaults(func=cmd_sql)

    a = p_.parse_args()
    try:
        a.func(a)
    except KeyboardInterrupt:
        print("\nInterrompido.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
