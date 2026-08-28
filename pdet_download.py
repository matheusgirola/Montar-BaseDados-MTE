#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 1 - Download idempotente dos microdados do PDET/MTE
=========================================================

Motor multiplataforma. NÃO chame este arquivo diretamente: use
`pdet.ps1` (Windows) ou `pdet.sh` (macOS/Linux), que ajustam o
ambiente antes (encoding, energia, caminhos, 7-Zip).

O que faz:
  - lê o inventário da Fase 0 (inventario_ftp.csv)
  - filtra o que você quer (base / ano / recorte)
  - baixa só o que falta ou mudou, comparando com o manifesto
  - retoma downloads interrompidos no meio do arquivo (comando FTP REST)
  - grava em .part e só renomeia depois de conferir o tamanho
  - registra sha256, bytes e data no manifesto
  - opcionalmente extrai os .7z

Rodar duas vezes não baixa nada de novo e não corrompe nada.
"""

from __future__ import annotations

import argparse
import csv
import ftplib
import hashlib
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MANIFESTO_CAMPOS = [
    "caminho_ftp", "arquivo_local", "bytes", "sha256",
    "modificado_ftp", "baixado_em", "status",
]

TIMEOUT = 120
MAX_TENTATIVAS = 5
BLOCO = 1024 * 1024          # 1 MB por bloco de leitura
RESERVA_DISCO = 5 * 1024**3  # margem de segurança: 5 GB


# --------------------------------------------------------------------------
# Utilidades multiplataforma
# --------------------------------------------------------------------------

WINDOWS = platform.system() == "Windows"

# Caracteres proibidos em nomes de arquivo no Windows.
PROIBIDOS_WIN = '<>:"|?*'


def caminho_seguro(base: Path, relativo: str) -> Path:
    """Converte um caminho do FTP em caminho local válido no SO atual."""
    partes = [p for p in relativo.replace("\\", "/").split("/") if p]
    limpas = []
    for p in partes:
        if WINDOWS:
            p = "".join("_" if c in PROIBIDOS_WIN else c for c in p)
            p = p.rstrip(". ")          # Windows não aceita ponto/espaço no fim
        limpas.append(p)
    destino = base.joinpath(*limpas)
    # Contorna o limite de 260 caracteres do Windows sem exigir registro.
    if WINDOWS and len(str(destino)) > 240 and not str(destino).startswith("\\\\?\\"):
        destino = Path("\\\\?\\" + str(destino.resolve()))
    return destino


def achar_7z() -> str | None:
    """Localiza o binário do 7-Zip em qualquer um dos três sistemas."""
    candidatos = ["7z", "7za", "7zz", "7zr"]
    if WINDOWS:
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            raiz = os.environ.get(var)
            if raiz:
                candidatos.insert(0, str(Path(raiz) / "7-Zip" / "7z.exe"))
    else:
        candidatos += ["/opt/homebrew/bin/7z", "/usr/local/bin/7z",
                       "/opt/homebrew/bin/7zz", "/usr/bin/7z"]
    for c in candidatos:
        achado = shutil.which(c) if os.sep not in c else (c if Path(c).exists() else None)
        if achado:
            return achado
    return None


def espaco_livre(caminho: Path) -> int:
    p = caminho
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def fmt(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.1f} {u}".replace(".", ",")
        n /= 1024
    return f"{n} B"


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Manifesto
# --------------------------------------------------------------------------

def ler_manifesto(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["caminho_ftp"]: r for r in csv.DictReader(fh)}


def gravar_manifesto(path: Path, registros: dict[str, dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFESTO_CAMPOS)
        w.writeheader()
        for r in sorted(registros.values(), key=lambda x: x["caminho_ftp"]):
            w.writerow(r)
    os.replace(tmp, path)   # atômico nos três sistemas


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

class Baixador:
    def __init__(self, host: str, port: int = 21, user: str = "anonymous",
                 passwd: str = "pdet@example.org", timeout: int = TIMEOUT):
        self.host, self.port = host, port
        self.user, self.passwd, self.timeout = user, passwd, timeout
        self.ftp: ftplib.FTP | None = None
        self.conectar()

    def conectar(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.close()
            except Exception:
                pass
        ftp = ftplib.FTP()
        ftp.encoding = "latin-1"
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.user, self.passwd)
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        self.ftp = ftp

    def info(self, caminho: str) -> tuple[int | None, str]:
        try:
            tam = self.ftp.size(caminho)
        except ftplib.all_errors:
            tam = None
        try:
            mod = self.ftp.voidcmd(f"MDTM {caminho}")[4:].strip()
        except ftplib.all_errors:
            mod = ""
        return tam, mod

    def baixar(self, caminho_ftp: str, destino: Path,
               tam_esperado: int | None = None) -> int:
        """Baixa com retomada. Retorna o tamanho final em bytes."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_suffix(destino.suffix + ".part")

        for tentativa in range(1, MAX_TENTATIVAS + 1):
            ja_tem = parcial.stat().st_size if parcial.exists() else 0
            if tam_esperado and ja_tem == tam_esperado:
                break
            if tam_esperado and ja_tem > tam_esperado:
                parcial.unlink()          # parcial corrompido
                ja_tem = 0
            try:
                modo = "ab" if ja_tem else "wb"
                t0, lidos = time.time(), ja_tem
                with open(parcial, modo) as fh:
                    def escrever(bloco: bytes) -> None:
                        nonlocal lidos
                        fh.write(bloco)
                        lidos += len(bloco)
                        if tam_esperado:
                            pct = 100 * lidos / tam_esperado
                            vel = (lidos - ja_tem) / max(time.time() - t0, 0.1)
                            print(f"\r    {pct:5.1f}%  {fmt(lidos)}  "
                                  f"{fmt(vel)}/s   ", end="", file=sys.stderr)

                    # REST: retoma do byte onde parou, em vez de recomeçar
                    self.ftp.retrbinary(f"RETR {caminho_ftp}", escrever,
                                        blocksize=BLOCO, rest=ja_tem or None)
                print("", file=sys.stderr)
                break
            except (ftplib.error_temp, ftplib.error_proto, socket.error,
                    EOFError, OSError) as e:
                espera = min(2 ** tentativa, 60)
                print(f"\n    [queda: {e} — retry {tentativa}/{MAX_TENTATIVAS} "
                      f"em {espera}s]", file=sys.stderr)
                time.sleep(espera)
                self.conectar()
            except ftplib.error_perm as e:
                raise RuntimeError(f"sem acesso a {caminho_ftp}: {e}") from e
        else:
            raise RuntimeError(f"falhou após {MAX_TENTATIVAS} tentativas: "
                               f"{caminho_ftp}")

        final = parcial.stat().st_size
        if tam_esperado and final != tam_esperado:
            raise RuntimeError(f"tamanho divergente em {caminho_ftp}: "
                               f"esperado {tam_esperado}, obtido {final}")
        os.replace(parcial, destino)
        return final

    def fechar(self) -> None:
        try:
            self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Seleção do que baixar
# --------------------------------------------------------------------------

# Pastas que o FTP mantém em paralelo à versão definitiva e que NÃO entram
# na base:
#
#   "2023 Parcial" / "2024 Parcial" — divulgação antecipada, com uma fração
#       dos vínculos do ano. Misturar com o definitivo duplica registros e
#       estraga qualquer comparação ano a ano.
#   ".../Legado/..."               — versão anterior do mesmo ano, mantida
#       para quem depende do formato antigo. É o mesmo dado, publicado duas
#       vezes; converter os dois dobra o ano.
#
# Ficam de fora por padrão, no download e na conversão. Para trazê-los de
# volta (por exemplo, para medir quanto o MTE revisou entre a parcial e a
# definitiva), use --incluir-parcial / --incluir-legado.
RE_PARCIAL = re.compile(r"(?i)parcial")
RE_LEGADO = re.compile(r"(?i)(?:^|[/\\])legado(?:[/\\]|$)")


def excluir_por_pasta(caminho: str, incluir_parcial: bool,
                      incluir_legado: bool) -> str:
    """Devolve o motivo da exclusão, ou '' se o arquivo deve entrar."""
    if not incluir_parcial and RE_PARCIAL.search(caminho):
        return "parcial"
    if not incluir_legado and RE_LEGADO.search(caminho):
        return "legado"
    return ""


def ler_lista(path: Path) -> list[str]:
    """Le o refazer_download.txt: um caminho do FTP por linha. Aceita
    linhas em branco e comentarios com #."""
    if not path.exists():
        sys.exit(f"ERRO: {path} nao existe.")
    itens = []
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        linha = linha.replace("\\", "/")
        if not linha.startswith("/"):
            linha = "/" + linha
        itens.append(linha)
    return itens


def selecionar_lista(inventario: Path, caminhos: list[str]) -> tuple[list[dict], list[str]]:
    """Seleciona exatamente os caminhos pedidos, sem nenhum outro filtro.

    Um pedido explicito passa por cima das exclusoes de parcial/legado: se
    voce listou, voce quer.
    """
    with open(inventario, encoding="utf-8", newline="") as fh:
        por_caminho = {r["caminho"].replace("\\", "/"): r
                       for r in csv.DictReader(fh)}
    achados, perdidos = [], []
    for c in caminhos:
        r = por_caminho.get(c)
        if r:
            achados.append(r)
        else:
            perdidos.append(c)
    return achados, perdidos


def selecionar(inventario: Path, bases, anos, recortes, extensoes,
               incluir_parcial: bool = False,
               incluir_legado: bool = False) -> tuple[list[dict], dict]:
    if not inventario.exists():
        sys.exit(f"ERRO: {inventario} não existe. Rode a Fase 0 primeiro:\n"
                 f"  python pdet_inventario.py crawl")
    with open(inventario, encoding="utf-8", newline="") as fh:
        linhas = list(csv.DictReader(fh))

    def ok(r: dict) -> bool:
        if bases and not any(r["base"].startswith(b) for b in bases):
            return False
        if anos and r["ano"] not in anos:
            return False
        if recortes and r["recorte"] not in recortes:
            return False
        if extensoes and r["extensao"] not in extensoes:
            return False
        return True

    escolhidos, excluidos = [], {"parcial": [], "legado": []}
    for r in linhas:
        if not ok(r):
            continue
        motivo = excluir_por_pasta(r["caminho"], incluir_parcial, incluir_legado)
        if motivo:
            excluidos[motivo].append(r)
        else:
            escolhidos.append(r)
    return escolhidos, excluidos


# --------------------------------------------------------------------------
# Extração
# --------------------------------------------------------------------------

def extrair(arquivo: Path, destino: Path, bin7z: str | None) -> bool:
    destino.mkdir(parents=True, exist_ok=True)
    if bin7z:
        cmd = [bin7z, "x", "-y", f"-o{destino}", str(arquivo)]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            return True
        print(f"    [7z falhou: {r.stderr.strip()[:200]}]", file=sys.stderr)
        return False
    try:
        import py7zr  # fallback puro-Python: mais lento, mas funciona em tudo
    except ImportError:
        print("    [sem 7-Zip e sem py7zr — instale um dos dois para extrair]",
              file=sys.stderr)
        return False
    with py7zr.SevenZipFile(arquivo, "r") as z:
        z.extractall(path=destino)
    return True


# --------------------------------------------------------------------------
# Fluxo principal
# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dados", required=True,
                   help="pasta raiz no drive (ex.: D:\\pdet ou /Volumes/Dados/pdet)")
    p.add_argument("--inventario", default="inventario_ftp.csv")
    p.add_argument("--host", default="ftp.mtps.gov.br")
    p.add_argument("--port", type=int, default=21)
    p.add_argument("--user", default="anonymous")
    p.add_argument("--passwd", default="pdet@example.org")
    p.add_argument("--base", action="append", default=[],
                   help="filtra por base; repetível (ex.: --base RAIS_VINCULOS)")
    p.add_argument("--ano", action="append", default=[])
    p.add_argument("--recorte", action="append", default=[],
                   help="ex.: --recorte NORDESTE")
    p.add_argument("--ext", action="append", default=["7z", "zip"])
    p.add_argument("--extrair", action="store_true")
    p.add_argument("--apagar-apos-extrair", action="store_true",
                   help="modo efêmero: descarta o .7z depois de extrair")
    p.add_argument("--lista", default="",
                   help="baixa exatamente os caminhos listados no arquivo "
                        "(um por linha), ignorando os demais filtros e "
                        "refazendo mesmo o que o manifesto marca como ok. "
                        "É o refazer_download.txt do pdet_verifica.py.")
    p.add_argument("--incluir-parcial", action="store_true",
                   help="baixa também as pastas 'AAAA Parcial' (divulgação "
                        "antecipada, incompleta). Fora por padrão.")
    p.add_argument("--incluir-legado", action="store_true",
                   help="baixa também as pastas 'Legado' (republicação do "
                        "mesmo ano em formato antigo). Fora por padrão.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sem-hash", action="store_true",
                   help="pula o sha256 (bem mais rápido em HD externo)")
    args = p.parse_args()

    raiz = Path(args.dados)
    raw = raiz / "00_raw"
    extraido = raiz / "00_extraido"
    manifesto_path = raiz / "03_meta" / "manifesto.csv"
    manifesto_path.parent.mkdir(parents=True, exist_ok=True)

    perdidos: list[str] = []
    excluidos: dict = {}
    if args.lista:
        alvos, perdidos = selecionar_lista(Path(args.inventario),
                                           ler_lista(Path(args.lista)))
    else:
        alvos, excluidos = selecionar(Path(args.inventario), args.base,
                                      args.ano, args.recorte, args.ext,
                                      args.incluir_parcial, args.incluir_legado)
    manifesto = ler_manifesto(manifesto_path)

    total = sum(int(r["bytes"]) for r in alvos if r["bytes"].isdigit())
    if args.lista:
        # o manifesto diz "ok" para esses arquivos -- foi justamente por
        # isso que eles passaram batido. Um pedido explicito refaz tudo.
        pendentes = list(alvos)
    else:
        pendentes = [r for r in alvos
                     if manifesto.get(r["caminho"], {}).get("bytes") != r["bytes"]
                     or manifesto.get(r["caminho"], {}).get("status") != "ok"]
    falta = sum(int(r["bytes"]) for r in pendentes if r["bytes"].isdigit())

    print(f"Sistema      : {platform.system()} {platform.release()}")
    print(f"Destino      : {raiz}")
    print(f"Selecionados : {len(alvos)} arquivos ({fmt(total)})")
    for motivo, itens in excluidos.items():
        if itens:
            b = sum(int(r["bytes"]) for r in itens if r["bytes"].isdigit())
            print(f"Excluídos    : {len(itens)} arquivos de pasta "
                  f"'{motivo}' ({fmt(b)}) — use --incluir-{motivo} para baixar")
    if perdidos:
        print(f"NAO achei no inventário: {len(perdidos)} caminho(s). O "
              f"inventário pode estar desatualizado —")
        print(f"                         rode 'pdet_inventario.py crawl "
              f"--force' e tente de novo.")
        for c in perdidos[:5]:
            print(f"   - {c}")
        if len(perdidos) > 5:
            print(f"   ... (+{len(perdidos) - 5})")
    print(f"Pendentes    : {len(pendentes)} arquivos ({fmt(falta)})")
    livre = espaco_livre(raiz)
    print(f"Espaço livre : {fmt(livre)}")

    if args.dry_run:
        for r in pendentes[:40]:
            print(f"  BAIXARIA {r['caminho']}  ({fmt(int(r['bytes'] or 0))})")
        if len(pendentes) > 40:
            print(f"  ... (+{len(pendentes) - 40})")
        return

    if not pendentes:
        print("Nada a fazer — tudo já está sincronizado.")
        return

    precisa = falta * (11 if args.extrair and not args.apagar_apos_extrair else 1)
    if livre < precisa + RESERVA_DISCO:
        sys.exit(f"ERRO: espaço insuficiente. Necessário ~{fmt(precisa)} "
                 f"+ {fmt(RESERVA_DISCO)} de reserva.\n"
                 f"Reduza o escopo (--ano/--recorte) ou use "
                 f"--apagar-apos-extrair.")

    bin7z = achar_7z() if args.extrair else None
    if args.extrair:
        print(f"7-Zip        : {bin7z or 'não encontrado (usará py7zr)'}")

    cli = Baixador(args.host, args.port, args.user, args.passwd)
    ok = erros = 0
    try:
        for i, r in enumerate(pendentes, 1):
            caminho_ftp = r["caminho"]
            destino = caminho_seguro(raw, caminho_ftp)
            tam = int(r["bytes"]) if r["bytes"].isdigit() else None
            print(f"[{i}/{len(pendentes)}] {caminho_ftp}  ({fmt(tam or 0)})")

            try:
                if args.lista and destino.exists():
                    # o arquivo local esta errado (truncado ou corrompido).
                    # Se ficar, o REST do FTP retomaria a partir do tamanho
                    # dele e o erro seria preservado.
                    destino.unlink()
                    parcial = destino.with_suffix(destino.suffix + ".part")
                    if parcial.exists():
                        parcial.unlink()
                tam_srv, mod_srv = cli.info(caminho_ftp)
                bytes_final = cli.baixar(caminho_ftp, destino, tam_srv or tam)
                registro = {
                    "caminho_ftp": caminho_ftp,
                    "arquivo_local": str(destino),
                    "bytes": str(bytes_final),
                    "sha256": "" if args.sem_hash else sha256(destino),
                    "modificado_ftp": mod_srv or r.get("modificado_em", ""),
                    "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": "ok",
                }

                if args.extrair:
                    alvo = caminho_seguro(extraido, caminho_ftp).parent
                    if extrair(destino, alvo, bin7z):
                        registro["status"] = "ok+extraido"
                        if args.apagar_apos_extrair:
                            destino.unlink()
                            registro["status"] = "extraido_bruto_descartado"

                manifesto[caminho_ftp] = registro
                ok += 1
            except Exception as e:
                print(f"    ERRO: {e}", file=sys.stderr)
                manifesto[caminho_ftp] = {
                    "caminho_ftp": caminho_ftp, "arquivo_local": str(destino),
                    "bytes": "", "sha256": "", "modificado_ftp": "",
                    "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": f"erro: {str(e)[:120]}",
                }
                erros += 1
            finally:
                gravar_manifesto(manifesto_path, manifesto)  # checkpoint a cada arquivo
    except KeyboardInterrupt:
        print("\nInterrompido. O .part fica salvo — rode de novo para retomar.",
              file=sys.stderr)
    finally:
        cli.fechar()
        gravar_manifesto(manifesto_path, manifesto)

    print(f"\nConcluído: {ok} ok, {erros} com erro. "
          f"Manifesto: {manifesto_path}")
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()