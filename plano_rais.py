#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plano_rais.py — decide EXATAMENTE o que baixar da RAIS, lendo o inventário
local. Não acessa o FTP.

O relatório agregado da Fase 0 não mostra os caminhos reais dos arquivos, e
sem eles não dá para saber, por exemplo, se a RAIS de 2023 está organizada
por região (NORDESTE) ou por UF (PI). Este script mostra isso e monta o
comando de download certo.

Uso:
    python plano_rais.py                          # anos 2022 a 2025
    python plano_rais.py --de 2019 --ate 2025
    python plano_rais.py --de 2022 --ate 2025 --uf PI
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

UFS = {"AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT","PA",
       "PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"}
NORDESTE = {"AL","BA","CE","MA","PB","PE","PI","RN","SE"}
REGIOES = {"CENTRO_OESTE","MG_ES_RJ","NORDESTE","NORTE","SUL","SP"}


def fmt(n):
    for u in ("B","KB","MB","GB","TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:,.1f} {u}".replace(",","_").replace(".",",").replace("_",".")
        n /= 1024


def eh_rais(r):
    c = r["caminho"].upper()
    return r["base"].startswith("RAIS") or "/RAIS" in c


def eh_doc(r):
    return (r["base"] == "AUXILIAR_DOC"
            or r["extensao"] in ("xls","xlsx","pdf","doc","docx","htm","html","txt"))


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", default="inventario_ftp.csv")
    p.add_argument("--de", type=int, default=2022)
    p.add_argument("--ate", type=int, default=2025)
    p.add_argument("--uf", default="PI", help="UF de interesse (padrão PI)")
    a = p.parse_args()

    if not os.path.exists(a.csv):
        sys.exit(f"ERRO: {a.csv} não encontrado. Rode este script na mesma "
                 f"pasta do inventário.")

    with open(a.csv, encoding="utf-8", newline="") as fh:
        todos = list(csv.DictReader(fh))
    for r in todos:
        r["_b"] = int(r["bytes"]) if r["bytes"].isdigit() else 0

    anos = [str(x) for x in range(a.de, a.ate + 1)]
    rais = [r for r in todos if eh_rais(r) and not eh_doc(r)]

    print("=" * 74)
    print(f"PLANO DE DOWNLOAD DA RAIS — anos {a.de} a {a.ate}")
    print("=" * 74)
    print(f"Inventário: {a.csv} | {len(todos)} arquivos | "
          f"RAIS (sem docs): {len(rais)}")

    # ------------------------------------------------------------------
    # 1. Que anos da RAIS existem, e com quantos arquivos
    # ------------------------------------------------------------------
    print("\n--- 1. Anos da RAIS presentes no FTP ---\n")
    por_ano = defaultdict(lambda: [0, 0])
    for r in rais:
        if r["ano"]:
            por_ano[r["ano"]][0] += 1
            por_ano[r["ano"]][1] += r["_b"]
    for ano in sorted(por_ano):
        n, b = por_ano[ano]
        marca = "  <== pedido" if ano in anos else ""
        print(f"  {ano}: {n:4d} arquivos, {fmt(b):>10}{marca}")

    faltando = [x for x in anos if x not in por_ano]
    if faltando:
        print(f"\n  !! ATENÇÃO: sem arquivos de RAIS para: {', '.join(faltando)}")

    # ------------------------------------------------------------------
    # 2. Como cada ano pedido está organizado
    # ------------------------------------------------------------------
    print("\n--- 2. Organização de cada ano pedido ---\n")
    alvo = [r for r in rais if r["ano"] in anos]
    if not alvo:
        sys.exit("Nenhum arquivo de RAIS nos anos pedidos. Confira --de/--ate.")

    for ano in anos:
        do_ano = [r for r in alvo if r["ano"] == ano]
        if not do_ano:
            print(f"  {ano}: (nada)\n")
            continue
        regs = sorted({r["recorte"] for r in do_ano
                       if r["recorte"] in REGIOES})
        ufs = sorted({r["recorte"] for r in do_ano
                      if r["recorte"] in UFS and r["recorte"] not in REGIOES})
        outros = [r for r in do_ano if not r["recorte"]]
        print(f"  {ano}: {len(do_ano)} arquivos, "
              f"{fmt(sum(r['_b'] for r in do_ano))}")
        if regs:
            print(f"     por REGIAO ({len(regs)}): {', '.join(regs)}")
        if ufs:
            print(f"     por UF ({len(ufs)}): {', '.join(ufs)}")
        if outros:
            print(f"     sem recorte ({len(outros)}): "
                  + ", ".join(sorted({r['arquivo'] for r in outros})[:4]))
        # diretorios distintos ajudam a entender a arvore
        dirs = sorted({r["diretorio"] for r in do_ano})
        for d in dirs[:4]:
            print(f"     dir: {d}")
        if len(dirs) > 4:
            print(f"     ... (+{len(dirs)-4} diretórios)")
        print()

    # ------------------------------------------------------------------
    # 3. Os arquivos concretos: NORDESTE vs UF de interesse
    # ------------------------------------------------------------------
    print(f"--- 3. Caminhos reais (região NORDESTE vs {a.uf}) ---\n")

    def mostra(rotulo, itens):
        if not itens:
            print(f"  {rotulo}: NENHUM arquivo encontrado\n")
            return 0
        tot = sum(r["_b"] for r in itens)
        print(f"  {rotulo}: {len(itens)} arquivos, {fmt(tot)}")
        for r in sorted(itens, key=lambda x: (x["ano"], x["arquivo"])):
            print(f"     [{r['ano']}] {fmt(r['_b']):>9}  {r['caminho']}")
        print()
        return tot

    nord = [r for r in alvo if r["recorte"] == "NORDESTE"]
    do_uf = [r for r in alvo if r["recorte"] == a.uf]
    b_nord = mostra("Regiao NORDESTE", nord)
    b_uf = mostra(f"UF {a.uf}", do_uf)

    # ------------------------------------------------------------------
    # 4. Veredito e comando pronto
    # ------------------------------------------------------------------
    print("=" * 74)
    print("RECOMENDACAO")
    print("=" * 74)

    anos_nord = {r["ano"] for r in nord}
    anos_uf = {r["ano"] for r in do_uf}
    cobre_nord = set(anos) <= anos_nord
    cobre_uf = set(anos) <= anos_uf

    if cobre_uf and b_uf and (not cobre_nord or b_uf < b_nord * 0.6):
        print(f"  Os arquivos por UF cobrem todos os anos pedidos e sao bem")
        print(f"  menores. Baixe so o {a.uf}: {fmt(b_uf)} contra "
              f"{fmt(b_nord)} do Nordeste.")
        recorte = a.uf
    elif cobre_nord:
        print(f"  Os arquivos regionais cobrem todos os anos pedidos.")
        if cobre_uf:
            print(f"  (Existe versao por UF tambem, com {fmt(b_uf)}, mas o")
            print(f"   recorte regional e o formato padrao dos anos recentes.)")
        print(f"  Use o recorte NORDESTE: {fmt(b_nord)} comprimido.")
        recorte = "NORDESTE"
    else:
        print("  Cobertura incompleta nos dois formatos. Anos disponiveis:")
        print(f"    NORDESTE: {', '.join(sorted(anos_nord)) or '-'}")
        print(f"    {a.uf}: {', '.join(sorted(anos_uf)) or '-'}")
        print("  Baixe ano a ano conferindo a secao 3 acima.")
        recorte = "NORDESTE"

    escolhido = do_uf if recorte == a.uf else nord
    tot = sum(r["_b"] for r in escolhido)
    bases = sorted({r["base"] for r in escolhido})

    print(f"\n  Volume comprimido : {fmt(tot)}")
    print(f"  Descompactado (~10x): {fmt(tot * 10)}")
    print(f"  Parquet (~1,6x)   : {fmt(tot * 1.6)}")
    print(f"  Bases envolvidas  : {', '.join(bases)}")
    print(f"\n  A 10 MB/s isso leva ~{tot / (10 * 1024**2) / 60:.0f} min "
          f"de download.")

    args_base = " ".join(f"-Base {b}" for b in bases)
    args_ano = ",".join(sorted(anos, reverse=True))
    print("\n  COMANDO (Windows) — confira primeiro com -DryRun:\n")
    print(f"    .\\pdet-windows.ps1 baixar -Conda -Dados D:\\pdet `")
    print(f"       {args_base} -Recorte {recorte} -Ano {args_ano} -DryRun")
    print("\n  Depois, para baixar de verdade, repita sem -DryRun.\n")


if __name__ == "__main__":
    main()