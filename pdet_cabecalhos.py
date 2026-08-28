#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2a - Sondagem de cabeçalhos da RAIS
=========================================

Lê APENAS as primeiras linhas de cada .txt de dentro dos .7z/.zip, sem
descompactar o arquivo inteiro, e confere o resultado contra o dicionário
de colunas montado a partir dos layouts oficiais (dic_rais.csv).

Serve para responder, antes de converter 400 GB: o esquema que o layout
oficial descreve é mesmo o que está no arquivo? E os anos sem layout
publicado (vínculos após 2020, estabelecimento após 2019) seguem o último
esquema conhecido?

MOTORES DE DESCOMPRESSÃO
------------------------
py7zr (padrão) : biblioteca Python, instala com `pip install py7zr` ou
                 `conda install -c conda-forge py7zr`. Não precisa de
                 administrador, o que resolve a vida em máquina corporativa.
                 Usa a API de WriterFactory, que entrega os blocos conforme
                 descomprime — o arquivo NÃO vai inteiro para a memória.
7z             : binário do 7-Zip, ~20% mais rápido. Use --motor 7z se ele
                 estiver instalado, ou --bin7z para apontar um 7za.exe
                 portátil que você tenha copiado para uma pasta.

Nos dois casos a leitura é abortada assim que a linha necessária é
encontrada, então a sondagem leva segundos por arquivo, não minutos.

USO
---
    python pdet_cabecalhos.py --raw E:\\pdet\\00_raw --amostra 3
    python pdet_cabecalhos.py --raw E:\\pdet\\00_raw
    python pdet_cabecalhos.py --raw E:\\pdet\\00_raw --motor 7z
    python pdet_cabecalhos.py --raw E:\\pdet\\00_raw --bin7z C:\\ferramentas\\7za.exe

SAÍDAS
------
    cabecalhos.csv        uma linha por arquivo interno encontrado
    cabecalhos.md         matriz coluna x ano + conferência contra o dicionário
    colunas_sugestao.csv  esqueleto de dicionário, caso apareça algo novo

Dependências: biblioteca padrão + py7zr (ou o binário do 7-Zip).
"""

from __future__ import annotations

import argparse
import codecs
import csv
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

LIMITE_BYTES = 8 * 1024 * 1024   # se não achar \n em 8 MB, algo está errado
EXT_DADOS = {".txt", ".csv", ".comt"}

RE_ANO = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")
UFS = {"AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"}
REGIOES = ["CENTRO_OESTE", "MG_ES_RJ", "NORDESTE", "NORTE", "SUL"]


# ===========================================================================
# Motores de leitura: py7zr, binário do 7-Zip e zipfile
# ===========================================================================

class PararLeitura(Exception):
    """Sentinela: já temos as linhas que queríamos, aborta a descompressão."""


def achar_7z(explicito: str | None = None) -> str | None:
    if explicito:
        p = Path(explicito)
        return str(p) if p.exists() else None
    candidatos = ["7z", "7za", "7zz", "7zr"]
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            raiz = os.environ.get(var)
            if raiz:
                candidatos.insert(0, str(Path(raiz) / "7-Zip" / "7z.exe"))
    else:
        candidatos += ["/opt/homebrew/bin/7z", "/usr/local/bin/7z", "/usr/bin/7z"]
    for c in candidatos:
        achado = shutil.which(c) if os.sep not in c else (c if Path(c).exists() else None)
        if achado:
            return achado
    return None


class Motor:
    """Interface comum: listar membros e ler as primeiras linhas de um deles."""

    def listar(self, arquivo: Path) -> list[tuple[str, int]]:
        raise NotImplementedError

    def primeiras_linhas(self, arquivo: Path, interno: str, n: int) -> list[bytes]:
        raise NotImplementedError


class MotorPy7zr(Motor):
    """Duas estratégias, escolhidas conforme a versão instalada.

    'factory' (py7zr >= 1.0): a API WriterFactory entrega os blocos conforme
        descomprime, e a gente aborta levantando uma exceção de dentro do
        write(). Nada toca o disco.

    'subprocesso' (py7zr < 1.0, sem o módulo py7zr.io): a única extração
        disponível escreve em disco e não dá para interromper de dentro.
        Então rodamos a extração num processo separado, vigiamos o arquivo
        temporário e matamos o processo assim que ele tem as linhas que
        interessam. O temporário nunca passa de alguns MB e é apagado
        em seguida. Medido: mesma velocidade da estratégia 'factory'.
    """
    nome = "py7zr"

    def __init__(self, tmp_base: str | None = None):
        try:
            import py7zr
        except ImportError:
            sys.exit(
                "ERRO: py7zr não está instalado.\n"
                "  pip install py7zr\n"
                "  (ou)  conda install -c conda-forge py7zr\n\n"
                "Nenhum dos dois precisa de privilégio de administrador.\n"
                "Se preferir usar o binário do 7-Zip: --motor 7z"
            )
        self.versao = getattr(py7zr, "__version__", "?")
        self.tmp_base = tmp_base or None
        try:
            import py7zr.io  # noqa: F401
            self.estrategia = "factory"
        except ImportError:
            self.estrategia = "subprocesso"
        self.nome = f"py7zr {self.versao} ({self.estrategia})"

    def listar(self, arquivo):
        import py7zr
        itens = []
        with py7zr.SevenZipFile(arquivo, "r") as z:
            for info in z.list():
                if getattr(info, "is_directory", False):
                    continue
                if Path(info.filename).suffix.lower() in EXT_DADOS:
                    itens.append((info.filename, int(info.uncompressed or 0)))
        return itens

    def primeiras_linhas(self, arquivo, interno, n):
        if self.estrategia == "factory":
            return self._por_factory(arquivo, interno, n)
        return self._por_subprocesso(arquivo, interno, n)

    # -- py7zr antigo: extrai num subprocesso e mata cedo -----------------
    def _por_subprocesso(self, arquivo, interno, n):
        import shutil as _shutil
        import subprocess as _sub
        import tempfile
        import time

        tmp = Path(tempfile.mkdtemp(prefix="pdet_cab_", dir=self.tmp_base))
        codigo = (
            "import sys, py7zr\n"
            "z = py7zr.SevenZipFile(sys.argv[1], 'r')\n"
            "z.extract(path=sys.argv[2], targets=[sys.argv[3]])\n"
        )
        proc = _sub.Popen([sys.executable, "-c", codigo,
                           str(arquivo), str(tmp), interno],
                          stdout=_sub.DEVNULL, stderr=_sub.PIPE)
        alvo = tmp.joinpath(*interno.replace("\\", "/").split("/"))
        buf = b""
        t0 = time.time()
        try:
            while True:
                candidato = alvo
                if not candidato.exists():
                    # algumas versões normalizam o caminho interno
                    achados = [q for q in tmp.rglob("*") if q.is_file()]
                    candidato = achados[0] if achados else None
                if candidato is not None and candidato.exists():
                    with open(candidato, "rb") as fh:
                        buf = fh.read(LIMITE_BYTES)
                    if buf.count(b"\n") >= n or len(buf) >= LIMITE_BYTES:
                        break
                if proc.poll() is not None:
                    break
                if time.time() - t0 > 300:
                    break
                time.sleep(0.05)
        finally:
            proc.kill()
            proc.wait()
            # no Windows o handle pode demorar um instante para liberar
            for _ in range(10):
                _shutil.rmtree(tmp, ignore_errors=True)
                if not tmp.exists():
                    break
                time.sleep(0.2)
        if not buf:
            erro = (proc.stderr.read() or b"").decode("utf-8", "replace")[:200]
            raise RuntimeError(f"extração não produziu saída. {erro}".strip())
        return buf.split(b"\n")[:n]

    # -- py7zr >= 1.0: streaming puro, sem tocar o disco -----------------
    def _por_factory(self, arquivo, interno, n):
        import py7zr
        from py7zr.io import Py7zIO, WriterFactory

        buffer = bytearray()

        class Coletor(Py7zIO):
            """Recebe os blocos do py7zr e interrompe assim que já bastam.

            Sem essa interrupção o py7zr descomprimiria os 30 GB do membro
            até o fim só para a gente ler a primeira linha.
            """
            def write(self, s):
                buffer.extend(bytes(s))
                if buffer.count(b"\n") >= n or len(buffer) >= LIMITE_BYTES:
                    raise PararLeitura
                return len(s)

            def read(self, size=None):
                return b""

            def seek(self, offset, whence=0):
                return 0

            def flush(self):
                return None

            def size(self):
                return len(buffer)

            def close(self):
                return None

        class Fabrica(WriterFactory):
            def create(self, filename):
                return Coletor()

        try:
            with py7zr.SevenZipFile(arquivo, "r") as z:
                z.extract(targets=[interno], factory=Fabrica())
        except PararLeitura:
            pass   # caminho normal: paramos de propósito
        return bytes(buffer).split(b"\n")[:n]


class Motor7z(Motor):
    nome = "7z"

    def __init__(self, binario: str):
        self.bin = binario

    def listar(self, arquivo):
        r = subprocess.run([self.bin, "l", "-slt", "-ba", str(arquivo)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(f"    [7z l falhou: {r.stderr.strip()[:150]}]", file=sys.stderr)
            return []
        itens, nome, tam, ehdir = [], None, 0, False
        for linha in r.stdout.splitlines():
            if linha.startswith("Path = "):
                nome, tam, ehdir = linha[7:].strip(), 0, False
            elif linha.startswith("Size = "):
                tam = int(linha[7:].strip() or 0)
            elif linha.startswith("Attributes = "):
                ehdir = "D" in linha[13:].strip()
            elif not linha.strip() and nome:
                if not ehdir and Path(nome).suffix.lower() in EXT_DADOS:
                    itens.append((nome, tam))
                nome = None
        if nome and not ehdir and Path(nome).suffix.lower() in EXT_DADOS:
            itens.append((nome, tam))
        return itens

    def primeiras_linhas(self, arquivo, interno, n):
        proc = subprocess.Popen(
            [self.bin, "e", "-so", "-bso0", "-bse0", str(arquivo), interno],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        buf = b""
        try:
            while buf.count(b"\n") < n and len(buf) < LIMITE_BYTES:
                pedaco = proc.stdout.read(65536)
                if not pedaco:
                    break
                buf += pedaco
        finally:
            # matar o processo é essencial: sem isso ele descomprime tudo
            try:
                proc.stdout.close()
            except OSError:
                pass
            proc.kill()
            proc.wait()
        return buf.split(b"\n")[:n]


class MotorZip(Motor):
    """Para os poucos .zip do FTP. zipfile é biblioteca padrão."""
    nome = "zipfile"

    def listar(self, arquivo):
        import zipfile
        with zipfile.ZipFile(arquivo) as z:
            return [(i.filename, i.file_size) for i in z.infolist()
                    if not i.is_dir()
                    and Path(i.filename).suffix.lower() in EXT_DADOS]

    def primeiras_linhas(self, arquivo, interno, n):
        import zipfile
        buf = b""
        with zipfile.ZipFile(arquivo) as z, z.open(interno) as fh:
            while buf.count(b"\n") < n and len(buf) < LIMITE_BYTES:
                pedaco = fh.read(65536)
                if not pedaco:
                    break
                buf += pedaco
        return buf.split(b"\n")[:n]


# ===========================================================================
# Análise do cabeçalho
# ===========================================================================

def decodificar(bruto: bytes) -> tuple[str, str]:
    """Devolve (texto, encoding). A ordem importa: latin-1 nunca falha, então
    testamos utf-8 primeiro. cp1252 é testado antes de latin-1 porque a faixa
    0x80-0x9F (aspas curvas, travessão) é indefinida em latin-1."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc), enc.replace("-sig", "")
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", "replace"), "latin-1(com perdas)"


def detectar_sep(linha: str) -> str:
    contagens = {sep: linha.count(sep) for sep in (";", "|", "\t", ",")}
    sep = max(contagens, key=contagens.get)
    return sep if contagens[sep] > 0 else ";"


def normalizar(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace('"', "").strip()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def meta_do_caminho(caminho: Path) -> tuple[str, str, str]:
    """(ano, recorte, base) inferidos do caminho. Heurística, não dogma."""
    alvo = str(caminho).upper().replace("\\", "/")
    anos = RE_ANO.findall(alvo)
    ano = anos[-1] if anos else ""

    recorte = ""
    nome = caminho.name.upper()
    for r in REGIOES:
        if r in nome:
            recorte = r
            break
    if not recorte:
        for uf in sorted(UFS):
            if re.search(rf"(?<![A-Z]){uf}(?![A-Z])", nome):
                recorte = uf
                break

    # A base é decidida pelo NOME DO ARQUIVO, não pelo caminho inteiro: uma
    # pasta chamada "estabelecimento" contaminava todos os arquivos dentro
    # dela. O caminho só entra como último recurso.
    #
    # Até 2017 os vínculos vêm num .7z por UF, com nome que é só a sigla mais
    # o ano (PI2017.7z), sem nenhuma palavra que diga o que são; e os
    # estabelecimentos vêm como ESTB####.7z, com "ESTB" e não "ESTAB".
    if re.search(r"\bEST(A?)B\b|EST(A?)B\d|^EST(A?)B", nome):
        base = "RAIS_ESTAB"
    elif "VINC" in nome:
        base = "RAIS_VINCULOS"
    elif re.search(r"\bDOM\b|RAIS_DOM", nome):
        base = "RAIS_DOMESTICO"
    elif re.match(rf"^({'|'.join(sorted(UFS))})\d{{4}}\b", nome):
        # PI2017.7z, SP2010.7z: arquivo de vínculos de uma UF
        base = "RAIS_VINCULOS"
    elif "ESTAB" in alvo or "ESTB" in alvo:
        base = "RAIS_ESTAB"
    elif "VINC" in alvo:
        base = "RAIS_VINCULOS"
    elif "/RAIS" in alvo:
        base = "RAIS_OUTRO"
    else:
        base = "OUTRO"
    return ano, recorte, base


# ===========================================================================
# Conferência contra o dicionário
# ===========================================================================

def carregar_dicionario(path: Path) -> dict:
    """{(base, ano_de, ano_ate): [linhas ordenadas por posicao]}"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        linhas = list(csv.DictReader(fh))
    esq = defaultdict(list)
    for r in linhas:
        esq[(r["base"], int(r["ano_de"]), int(r["ano_ate"]))].append(r)
    for k in esq:
        esq[k].sort(key=lambda r: int(r["posicao"]))
    return dict(esq)


def rotulo_dic(r: dict) -> str:
    """O dicionário mudou de nome de coluna entre versões; aceita as duas."""
    return r.get("header_arquivo") or r.get("header_provavel") or ""


def conferir(esquemas: dict, base: str, ano: str,
             colunas: list[str]) -> dict:
    """Compara o cabeçalho lido com os esquemas conhecidos.

    Devolve o melhor candidato e o veredito. O casamento é por número de
    colunas primeiro e por nome normalizado depois — assim funciona mesmo
    quando a heurística de caminho errou a base ou o ano.
    """
    if not esquemas:
        return {"veredito": "sem dicionário", "esquema": "", "detalhe": ""}

    lidas = [normalizar(c) for c in colunas]
    conj_lidas = set(lidas)

    candidatos = []
    for (b, a1, a2), regs in esquemas.items():
        esperadas = [normalizar(rotulo_dic(r)) for r in regs]
        inter = len(conj_lidas & set(esperadas))
        pontos = inter * 10
        if len(regs) == len(lidas):
            pontos += 50
        if base in (b, "RAIS_OUTRO", "OUTRO"):
            pontos += 5
        if ano.isdigit() and a1 <= int(ano) <= a2:
            pontos += 5
        candidatos.append((pontos, inter, (b, a1, a2), regs, esperadas))

    candidatos.sort(key=lambda x: -x[0])
    _, inter, chave, regs, esperadas = candidatos[0]
    rotulo = f"{chave[0]} {chave[1]}-{chave[2]}"

    if len(regs) != len(lidas):
        det = f"esperava {len(regs)} colunas, li {len(lidas)}"
        return {"veredito": "DIVERGE", "esquema": rotulo, "detalhe": det}

    difs = [f"pos {i + 1}: dicionário='{rotulo_dic(regs[i])}' "
            f"arquivo='{colunas[i]}'"
            for i in range(len(lidas)) if lidas[i] != esperadas[i]]
    if not difs:
        return {"veredito": "OK", "esquema": rotulo, "detalhe": ""}
    return {"veredito": f"OK (nº de colunas) / {len(difs)} rótulo(s) diferentes",
            "esquema": rotulo, "detalhe": " | ".join(difs[:6])}


# ===========================================================================
# Principal
# ===========================================================================

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", required=True,
                   help="pasta com os arquivos baixados (ex.: E:\\pdet\\00_raw)")
    p.add_argument("--filtro", default="RAIS",
                   help="só processa caminhos contendo este texto "
                        "(padrão RAIS; use '' para todos)")
    p.add_argument("--amostra", type=int, default=0, metavar="N",
                   help="processa só os N primeiros arquivos (teste rápido)")
    p.add_argument("--motor", choices=["auto", "py7zr", "7z"], default="auto",
                   help="auto = py7zr se disponível, senão o binário do 7-Zip")
    p.add_argument("--bin7z", default="",
                   help="caminho de um 7z.exe/7za.exe (inclusive portátil)")
    p.add_argument("--dic", default="dic_rais.csv",
                   help="dicionário de colunas para conferência")
    p.add_argument("--saida", default=".", help="pasta das saídas")
    p.add_argument("--tmp", default="",
                   help="pasta temporária usada pelo py7zr antigo; aponte para "
                        "o disco interno, fora de OneDrive/rede")
    a = p.parse_args()

    raiz = Path(a.raw)
    if not raiz.exists():
        sys.exit(f"ERRO: {raiz} não existe.")
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)

    # --- escolha do motor ---------------------------------------------
    bin7z = achar_7z(a.bin7z or None)
    if a.motor == "7z":
        if not bin7z:
            sys.exit("ERRO: --motor 7z pedido, mas não achei o binário.\n"
                     "  Aponte com --bin7z C:\\caminho\\7za.exe\n"
                     "  ou use --motor py7zr (pip install py7zr).")
        motor = Motor7z(bin7z)
    elif a.motor == "py7zr":
        motor = MotorPy7zr(a.tmp or None)
    else:
        try:
            import py7zr  # noqa: F401
            motor = MotorPy7zr(a.tmp or None)
        except ImportError:
            if not bin7z:
                sys.exit("ERRO: nem py7zr nem o binário do 7-Zip disponíveis.\n"
                         "  pip install py7zr   (não precisa de administrador)")
            motor = Motor7z(bin7z)
    motor_zip = MotorZip()
    print(f"Motor : {motor.nome}"
          + (f" ({bin7z})" if isinstance(motor, Motor7z) else ""), file=sys.stderr)
    if getattr(motor, "estrategia", "") == "subprocesso":
        print("        (py7zr anterior à 1.0: sem a API de streaming. Funciona "
              "igual,\n         só passa por um temporário de poucos MB. "
              "'pip install -U py7zr'\n         elimina isso, mas não é "
              "necessário.)", file=sys.stderr)

    esquemas = carregar_dicionario(Path(a.dic))
    print(f"Dicionário : {a.dic} "
          f"({len(esquemas)} esquemas)" if esquemas
          else f"Dicionário : {a.dic} não encontrado — sem conferência",
          file=sys.stderr)

    arquivos = sorted(q for q in raiz.rglob("*")
                      if q.suffix.lower() in (".7z", ".zip")
                      and a.filtro.upper() in str(q).upper())
    if a.amostra:
        arquivos = arquivos[:a.amostra]
    if not arquivos:
        sys.exit(f"ERRO: nenhum .7z/.zip em {raiz} com o filtro '{a.filtro}'.")
    print(f"Arquivos a sondar: {len(arquivos)}\n", file=sys.stderr)

    registros = []
    for i, arq in enumerate(arquivos, 1):
        print(f"[{i}/{len(arquivos)}] {arq.name}", file=sys.stderr, flush=True)
        m = motor_zip if arq.suffix.lower() == ".zip" else motor
        try:
            internos = m.listar(arq)
        except Exception as e:
            print(f"    !! não consegui listar: {e}", file=sys.stderr)
            continue
        if not internos:
            print("    (nenhum .txt/.csv/.comt dentro)", file=sys.stderr)
            continue

        for interno, tam in internos:
            try:
                linhas = m.primeiras_linhas(arq, interno, n=2)
            except Exception as e:
                print(f"    !! {interno}: {e}", file=sys.stderr)
                continue
            if not linhas or not linhas[0]:
                print(f"    !! {interno}: primeira linha vazia", file=sys.stderr)
                continue

            cab_txt, enc = decodificar(linhas[0].rstrip(b"\r"))
            sep = detectar_sep(cab_txt)
            colunas = [c.strip().strip('"') for c in cab_txt.split(sep)]
            amostra = ""
            if len(linhas) > 1 and linhas[1]:
                amostra, _ = decodificar(linhas[1].rstrip(b"\r"))

            # decimal com vírgula deixa rastro: "1234,56" entre separadores
            virgula_dec = bool(re.search(r"\d,\d{2}(?:$|" + re.escape(sep) + ")",
                                         amostra))
            ano, recorte, base = meta_do_caminho(arq)
            conf = conferir(esquemas, base, ano, colunas)

            registros.append({
                "arquivo": str(arq), "arquivo_interno": interno,
                "bytes_internos": tam, "base": base, "ano": ano,
                "recorte": recorte, "encoding": enc, "separador": repr(sep),
                "decimal_virgula": "sim" if virgula_dec else "?",
                "n_colunas": len(colunas),
                "esquema_casado": conf["esquema"], "veredito": conf["veredito"],
                "divergencias": conf["detalhe"],
                "colunas": sep.join(colunas),
                "amostra_1a_linha": amostra[:400],
            })
            marca = "OK " if conf["veredito"] == "OK" else "!! "
            print(f"    {marca}{interno}: {len(colunas)} col, {enc}, "
                  f"sep={sep!r}, decimal_virgula="
                  f"{'sim' if virgula_dec else '?'} -> "
                  f"{conf['esquema']} [{conf['veredito']}]", file=sys.stderr)
            if conf["detalhe"]:
                print(f"       {conf['detalhe'][:200]}", file=sys.stderr)

    if not registros:
        sys.exit("Nada foi lido. Confira --raw e --filtro.")

    # --- cabecalhos.csv ------------------------------------------------
    csv_path = saida / "cabecalhos.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(registros[0].keys()))
        w.writeheader()
        w.writerows(registros)

    # --- cabecalhos.md -------------------------------------------------
    md = ["# Cabeçalhos reais da RAIS\n",
          f"- Arquivos sondados: {len(registros)}",
          f"- Fonte: `{raiz}`",
          f"- Motor: {motor.nome}\n",
          "\n## Conferência contra o dicionário\n",
          "| arquivo | ano | recorte | col | esquema casado | veredito |",
          "|---|---|---|---|---|---|"]
    for r in sorted(registros, key=lambda x: (x["ano"], x["arquivo"])):
        md.append(f"| `{Path(r['arquivo']).name}` | {r['ano']} | "
                  f"{r['recorte']} | {r['n_colunas']} | {r['esquema_casado']} "
                  f"| {r['veredito']} |")

    divergentes = [r for r in registros if r["veredito"] != "OK"]
    if divergentes:
        md.append("\n### Divergências detalhadas\n")
        for r in divergentes:
            md.append(f"- **{Path(r['arquivo']).name}** "
                      f"({r['n_colunas']} colunas, {r['esquema_casado']}): "
                      f"{r['divergencias'] or r['veredito']}")

    # matriz coluna x ano, por base
    ocorr: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    ordem: dict = defaultdict(dict)
    anos_por_base: dict = defaultdict(set)
    for r in registros:
        sep = r["separador"].strip("'\"")
        if sep == "\\t":
            sep = "\t"
        for pos, bruto in enumerate(r["colunas"].split(sep)):
            chave = normalizar(bruto)
            if not chave:
                continue
            ocorr[r["base"]][chave][r["ano"]].add(bruto)
            ordem[r["base"]].setdefault(chave, pos)
            anos_por_base[r["base"]].add(r["ano"])

    for base in sorted(ocorr):
        anos = sorted(x for x in anos_por_base[base] if x)
        md.append(f"\n## {base} — coluna x ano\n")
        md.append("| coluna (normalizada) | " + " | ".join(anos) + " |")
        md.append("|" + "---|" * (len(anos) + 1))
        for chave in sorted(ocorr[base], key=lambda k: ordem[base][k]):
            cel = ["x" if ocorr[base][chave].get(ano) else "." for ano in anos]
            md.append(f"| `{chave}` | " + " | ".join(cel) + " |")
        variacoes = []
        for chave, por_ano in ocorr[base].items():
            todos = set()
            for s in por_ano.values():
                todos |= s
            if len(todos) > 1:
                variacoes.append((chave, sorted(todos)))
        if variacoes:
            md.append("\n### Rótulos que variam entre arquivos\n")
            for chave, rots in sorted(variacoes):
                md.append(f"- `{chave}`: " + " / ".join(f"`{x}`" for x in rots))

    (saida / "cabecalhos.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # --- esqueleto de dicionário ---------------------------------------
    dic_path = saida / "colunas_sugestao.csv"
    with open(dic_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["base", "chave_normalizada", "nome_canonico", "tipo",
                    "anos_presentes", "rotulos_brutos"])
        for base in sorted(ocorr):
            for chave in sorted(ocorr[base], key=lambda k: ordem[base][k]):
                por_ano = ocorr[base][chave]
                rots = sorted({x for s in por_ano.values() for x in s})
                w.writerow([base, chave, chave, "",
                            ",".join(sorted(x for x in por_ano if x)),
                            " | ".join(rots)])

    n_ok = sum(1 for r in registros if r["veredito"] == "OK")
    print(f"\n{n_ok}/{len(registros)} arquivos batem exatamente com o dicionário.",
          file=sys.stderr)
    print(f"  {csv_path}\n  {saida / 'cabecalhos.md'}\n  {dic_path}",
          file=sys.stderr)
    if divergentes:
        print(f"\n{len(divergentes)} arquivo(s) com divergência — veja a seção "
              f"'Divergências detalhadas' do .md antes de converter.",
              file=sys.stderr)


if __name__ == "__main__":
    main()