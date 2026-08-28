#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdet_verifica.py — descobre por que um .7z falhou na conversão
===============================================================

Responde tres perguntas, nesta ordem:

  1. O arquivo local tem o mesmo tamanho do que esta no FTP?
     A comparacao e feita pelo CAMINHO COMPLETO, nunca pelo nome. No FTP
     do PDET o mesmo nome aparece em varias pastas com tamanhos
     diferentes -- "CAGEDESTAB202001.7z" existe em uma dezena de pastas
     mensais. Comparar por nome produz "truncado" onde nao ha nada de
     errado, inclusive com diferenca negativa, que e impossivel.

  2. O arquivo descomprime inteiro?
     Aqui a descompressao acontece de verdade, do inicio ao fim. Nao
     usamos py7zr.test(), que so confere o cabecalho e volta em
     milissegundos dando "ok" para arquivo quebrado. Um .7z de 700 MB
     leva minutos para ser testado, e e assim que tem que ser.

  3. Os dois motores concordam?
     Se o binario do 7-Zip abre e o py7zr nao, o arquivo esta bom e o
     problema e da biblioteca -- e a solucao e converter com o binario,
     nao baixar de novo.

Uso:
    python pdet_verifica.py --manifesto E:\\pdet\\03_meta\\conversao.csv
    python pdet_verifica.py --arquivo "E:\\pdet\\00_raw\\...\\SP2015.7z"
    python pdet_verifica.py --manifesto ... --so-tamanho    # rapido
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

csv.field_size_limit(10 ** 7)
BLOCO = 1 << 20


def fmt(n: float) -> str:
    s = "-" if n < 0 else ""
    n = abs(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{s}{n:.1f} {u}".replace(".", ",")
        n /= 1024
    return f"{s}{n} B"


def achar_7z(explicito=None):
    if explicito:
        return explicito if Path(explicito).exists() else None
    cand = ["7z", "7za", "7zz", "7zr"]
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            raiz = os.environ.get(var)
            if raiz:
                cand.insert(0, str(Path(raiz) / "7-Zip" / "7z.exe"))
    else:
        cand += ["/opt/homebrew/bin/7z", "/usr/local/bin/7z", "/usr/bin/7z"]
    for c in cand:
        a = shutil.which(c) if os.sep not in c else (c if Path(c).exists() else None)
        if a:
            return a
    return None


def caminho_ftp(local: Path) -> str:
    """E:\\pdet\\00_raw\\pdet\\microdados\\RAIS\\2015\\SP2015.7z
       -> /pdet/microdados/RAIS/2015/SP2015.7z"""
    p = str(local).replace("\\", "/")
    i = p.lower().find("00_raw/")
    return "/" + p[i + 7:].lstrip("/") if i >= 0 else p


# ---------------------------------------------------------------------------
# Testes de integridade — os dois descomprimem de verdade
# ---------------------------------------------------------------------------

def testar_binario(arquivo: Path, bin7z: str) -> tuple[bool, str]:
    r = subprocess.run([bin7z, "t", str(arquivo)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return True, "ok"
    msg = (r.stdout or "") + (r.stderr or "")
    linha = next((l.strip() for l in msg.splitlines()
                  if "ERROR" in l.upper() or "Corrupt" in l or "CRC" in l), "")
    return False, linha[:110] or f"7z retornou {r.returncode}"


def testar_py7zr(arquivo: Path) -> tuple[bool, str, int]:
    """Reproduz exatamente o caminho que o conversor usa, para que um
    'ok' aqui signifique mesmo que a conversao vai passar."""
    import py7zr
    try:
        from py7zr.io import Py7zIO, WriterFactory
        lidos = [0]

        class Sumidouro(Py7zIO):
            def write(self, s):
                lidos[0] += len(s)
                return len(s)

            def read(self, size=None):
                return b""

            def seek(self, o, w=0):
                return 0

            def flush(self):
                return None

            def size(self):
                return lidos[0]

            def close(self):
                return None

        class Fabrica(WriterFactory):
            def create(self, filename):
                return Sumidouro()

        with py7zr.SevenZipFile(arquivo, "r") as z:
            z.extract(factory=Fabrica())
        return True, "ok", lidos[0]
    except ImportError:
        # py7zr antigo: testzip() descomprime mesmo (test() nao)
        try:
            with py7zr.SevenZipFile(arquivo, "r") as z:
                ruim = z.testzip()
            if ruim:
                return False, f"CRC falhou em {ruim}", 0
            return True, "ok", 0
        except Exception as e:                               # noqa: BLE001
            return False, f"{type(e).__name__}: {str(e)[:90]}", 0
    except Exception as e:                                   # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:90]}", 0


# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifesto", default="",
                   help="conversao.csv: verifica os que deram erro")
    p.add_argument("--arquivo", action="append", default=[])
    p.add_argument("--inventario", default="inventario_ftp.csv")
    p.add_argument("--saida", default="refazer_download.txt")
    p.add_argument("--todos", action="store_true",
                   help="verifica tudo do manifesto, nao so o que falhou")
    p.add_argument("--so-tamanho", action="store_true",
                   help="pula a descompressao (segundos em vez de minutos)")
    p.add_argument("--bin7z", default="")
    a = p.parse_args()

    alvos: list[Path] = [Path(x) for x in a.arquivo]
    if a.manifesto:
        m = Path(a.manifesto)
        if not m.exists():
            sys.exit(f"ERRO: {m} nao existe.")
        with open(m, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if a.todos or r["status"] != "ok":
                    q = Path(r["arquivo"])
                    if q not in alvos:
                        alvos.append(q)
    if not alvos:
        sys.exit("Nada a verificar. Use --manifesto ou --arquivo.")
    alvos = sorted(set(alvos))

    # tamanhos do FTP, indexados pelo CAMINHO, nao pelo nome
    tam_ftp: dict[str, int] = {}
    inv = Path(a.inventario)
    if inv.exists():
        with open(inv, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("bytes", "")).isdigit():
                    tam_ftp[r["caminho"].replace("\\", "/").lower()] = int(r["bytes"])
        print(f"Inventario   : {inv} ({len(tam_ftp)} caminhos)")
    else:
        print(f"AVISO: {inv} nao encontrado — sem comparacao de tamanho.")

    bin7z = achar_7z(a.bin7z or None)
    tem_py7zr = True
    try:
        import py7zr  # noqa: F401
    except ImportError:
        tem_py7zr = False
    print(f"7-Zip        : {bin7z or 'ausente'}")
    print(f"py7zr        : {'presente' if tem_py7zr else 'ausente'}")
    if a.so_tamanho:
        print("Modo         : so tamanho (sem descompressao)")
    print(f"A verificar  : {len(alvos)} arquivo(s)\n")

    ok, difere, quebrado, so_py7zr, sumido = [], [], [], [], []

    for i, q in enumerate(alvos, 1):
        print(f"[{i}/{len(alvos)}] {q.name}", end=" ", flush=True)
        if not q.exists():
            print("-> NAO EXISTE no disco")
            sumido.append(q)
            continue

        local = q.stat().st_size
        esperado = tam_ftp.get(caminho_ftp(q).lower())
        if esperado is not None and local != esperado:
            d = local - esperado
            rotulo = "MENOR que o FTP" if d < 0 else "MAIOR que o FTP"
            print(f"-> TAMANHO DIFERE ({rotulo}): local {fmt(local)}, "
                  f"FTP {fmt(esperado)}, diferenca {fmt(d)}")
            difere.append((q, d))
            continue
        if a.so_tamanho:
            print(f"-> tamanho confere ({fmt(local)})")
            ok.append(q)
            continue

        # descompressao de verdade
        t0 = time.time()
        r_bin = testar_binario(q, bin7z) if bin7z else None
        r_py = testar_py7zr(q) if tem_py7zr else None
        dt = time.time() - t0

        bin_ok = r_bin[0] if r_bin else None
        py_ok = r_py[0] if r_py else None

        if bin_ok is True and py_ok is False:
            print(f"-> 7-Zip abre, py7zr NAO ({r_py[1]}) [{dt:.0f}s]")
            so_py7zr.append(q)
        elif (bin_ok is False) or (py_ok is False):
            motivo = (r_bin[1] if bin_ok is False else r_py[1])
            print(f"-> CORROMPIDO: {motivo} [{dt:.0f}s]")
            quebrado.append(q)
        else:
            desc = f", {fmt(r_py[2])} descomprimidos" if r_py and r_py[2] else ""
            print(f"-> integro ({fmt(local)}{desc}, {dt:.0f}s)")
            ok.append(q)

    print("\n" + "=" * 68)
    print(f"integros            : {len(ok)}")
    print(f"tamanho diferente   : {len(difere)}")
    print(f"corrompidos         : {len(quebrado)}")
    print(f"so o py7zr recusa   : {len(so_py7zr)}")
    if sumido:
        print(f"nao existem         : {len(sumido)}")

    default_path = r"C:\..."
    if so_py7zr:
        print("\n" + "-" * 68)
        print("ARQUIVOS QUE O 7-ZIP ABRE E O py7zr RECUSA")
        print("-" * 68)
        print("Estes arquivos estao INTEGROS. Nao adianta baixar de novo: o")
        print("problema e a biblioteca, nao o dado. Converta-os apontando o")
        print("binario do 7-Zip, que o conversor prefere quando existe:")
        print(f"\n  set PATH=%PATH%;{Path(bin7z).parent if bin7z else default_path}")
        print("  uv run python pdet_parquet.py --raw E:\\pdet\\00_raw ...")
        for q in so_py7zr[:6]:
            print(f"    - {q.name}")

    if difere:
        print("\n" + "-" * 68)
        print("TAMANHO DIFERENTE DO FTP")
        print("-" * 68)
        menores = [q for q, d in difere if d < 0]
        maiores = [q for q, d in difere if d > 0]
        if menores:
            print(f"{len(menores)} menor(es) que o FTP: download incompleto, "
                  f"baixe de novo.")
        if maiores:
            print(f"{len(maiores)} MAIOR(es) que o FTP. Isso nao e truncamento.")
            print("Em geral significa que o FTP publicou uma versao nova e")
            print("menor do arquivo depois que voce baixou, ou que o")
            print("inventario esta velho. Rode o inventario de novo antes de")
            print("apagar qualquer coisa:")
            print("    uv run python pdet_inventario.py crawl --force")

    refazer = [q for q, d in difere if d < 0] + quebrado + sumido
    if refazer:
        Path(a.saida).write_text(
            "\n".join(caminho_ftp(q) for q in refazer) + "\n", encoding="utf-8")
        print(f"\nPrecisam ser baixados de novo: {len(refazer)} "
              f"(lista em {a.saida})")
        for q in refazer[:6]:
            print(f'  Remove-Item "{q}"')
        if len(refazer) > 6:
            print(f"  ... (+{len(refazer) - 6})")
    elif not so_py7zr:
        print("\nNenhum arquivo precisa ser baixado de novo.")


if __name__ == "__main__":
    main()