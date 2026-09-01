#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2 - Conversão da RAIS para Parquet particionado
=====================================================

Lê os .7z baixados e grava Parquet particionado por ano/UF, sem nunca
materializar o .txt inteiro em disco (quando o py7zr permite).

A UNIDADE DE TRABALHO é um arquivo interno dentro de um .7z. Cada unidade
concluída vira uma linha no manifesto. Rodar de novo pula tudo que já está
lá: não existe "recomeçar do zero".

PRINCÍPIOS
----------
1. Tudo é lido como TEXTO e convertido depois, em SQL. Os arquivos da RAIS
   têm zeros à esquerda, espaços de preenchimento, decimal com vírgula em
   uns anos e ponto em outros, e ausentes escritos de seis formas
   diferentes. Deixar o parser adivinhar é como se perde dado em silêncio.

2. As colunas são lidas por POSIÇÃO, não por nome. O cabeçalho é
   descartado e os nomes vêm do dicionário. Isso torna irrelevante que o
   MTE tenha renomeado tudo em 2023.

3. A saída de cada unidade é montada numa pasta de estágio e só é movida
   para a árvore final quando termina. Queda de energia no meio não deixa
   Parquet pela metade na base.

USO
---
    python pdet_parquet.py --raw E:\\pdet\\00_raw --saida E:\\pdet\\10_parquet
    python pdet_parquet.py --raw ... --saida ... --dry-run
    python pdet_parquet.py --raw ... --saida ... --ate-hora 17:20
    python pdet_parquet.py --raw ... --saida ... --paralelo 3 --ano 2023 --ano 2024
    python pdet_parquet.py --raw ... --saida ... --refazer --ano 2019

Dependências: duckdb, pyarrow, py7zr (ou o binário do 7-Zip).
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
import hashlib
import tempfile
import threading
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

EXT_DADOS = {".txt", ".csv", ".comt"}
BLOCO = 1 << 20
MANIFESTO_CAMPOS = [
    "chave", "arquivo", "arquivo_interno", "base", "ano", "recorte",
    "esquema", "linhas", "bytes_lidos", "bytes_parquet", "particoes",
    "segundos", "convertido_em", "status",
]

RE_ANO = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")

# Pastas que o FTP mantém em paralelo à versão definitiva e que NÃO entram
# na base:
#
#   "2023 Parcial" / "2024 Parcial" — divulgação antecipada, com uma fração
#       dos vínculos do ano. Misturar com o definitivo duplica registros e
#       estraga a comparação ano a ano.
#   ".../Legado/..."               — republicação do mesmo ano em formato
#       antigo. É o mesmo dado duas vezes; converter os dois dobra o ano.
#
# Ficam de fora por padrão. --incluir-parcial / --incluir-legado trazem de
# volta, caso um dia você queira medir quanto o MTE revisou entre uma
# versão e outra.
RE_PARCIAL = re.compile(r"(?i)parcial")
RE_LEGADO = re.compile(r"(?i)(?:^|[/\\])legado(?:[/\\]|$)")


def excluir_por_pasta(caminho: str, incluir_parcial: bool,
                      incluir_legado: bool) -> str:
    """Devolve o motivo da exclusão, ou '' se o arquivo deve entrar."""
    if not incluir_parcial and RE_PARCIAL.search(caminho):
        return "pasta parcial (divulgação antecipada)"
    if not incluir_legado and RE_LEGADO.search(caminho):
        return "pasta Legado (republicação do mesmo ano)"
    return ""
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"]
REGIOES = ["CENTRO_OESTE", "MG_ES_RJ", "NORDESTE", "NORTE", "SUL"]

# Código IBGE de UF -> sigla. A RAIS grava município com 6 dígitos (sem o
# dígito verificador), e os 2 primeiros são a UF.
COD_UF = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}


# ===========================================================================
# Classificação (mesmas regras do pdet_cabecalhos.py)
# ===========================================================================

def meta_do_caminho(caminho: Path) -> tuple[str, str, str]:
    alvo = str(caminho).upper().replace("\\", "/")
    nome = caminho.name.upper()
    anos = RE_ANO.findall(alvo)
    ano = anos[-1] if anos else ""

    recorte = ""
    for r in REGIOES:
        if r in nome:
            recorte = r
            break
    if not recorte:
        for uf in UFS:
            if re.search(rf"(?<![A-Z]){uf}(?![A-Z])", nome):
                recorte = uf
                break

    # O CAGED tem que sair na frente. "CAGEDESTAB202001.7z" casa com a regra
    # de estabelecimento e, sem esta checagem, um arquivo do Novo CAGED entra
    # com o esquema da RAIS -- 13 colunas contra 24, e o parser morre. O
    # mesmo vale para a pasta "NOVO CAGED/Legado/Estabelecimentos", cujo
    # nome contem "ESTAB".
    if re.search(r"CAGED", alvo):
        return ano, recorte, "CAGED"

    if re.search(r"\bEST(A?)B\b|EST(A?)B\d|^EST(A?)B", nome):
        base = "RAIS_ESTAB"
    elif "VINC" in nome:
        base = "RAIS_VINCULOS"
    elif re.search(r"\bDOM\b|RAIS_DOM", nome):
        base = "RAIS_DOMESTICO"
    elif re.match(rf"^({'|'.join(UFS)})\d{{4}}\b", nome):
        base = "RAIS_VINCULOS"
    elif "ESTAB" in alvo or "ESTB" in alvo:
        base = "RAIS_ESTAB"
    elif "VINC" in alvo:
        base = "RAIS_VINCULOS"
    else:
        base = "RAIS_OUTRO"
    return ano, recorte, base


# ===========================================================================
# Dicionário de esquemas
# ===========================================================================

class Esquema:
    def __init__(self, base, ano_de, ano_ate, linhas):
        self.base, self.ano_de, self.ano_ate = base, int(ano_de), int(ano_ate)
        self.linhas = sorted(linhas, key=lambda r: int(r["posicao"]))
        p = self.linhas[0]
        self.separador = p["separador"] or ";"
        self.decimal = p["decimal"] or ","
        self.aspas = p["aspas"] or ""
        self.encoding = p["encoding"] or "cp1252"
        self.nulos = [x for x in (p["nulos"] or "").split("|") if x]
        self.colunas = [r["nome_canonico"] for r in self.linhas]
        self.tipos = [r["tipo"] for r in self.linhas]

    @property
    def rotulo(self):
        return (f"{self.base} {self.ano_de}"
                + (f"-{self.ano_ate}" if self.ano_ate != self.ano_de else ""))

    def __len__(self):
        return len(self.linhas)


def carregar_esquemas(path: Path) -> list[Esquema]:
    if not path.exists():
        sys.exit(f"ERRO: dicionário {path} não encontrado.\n"
                 f"Rode o pdet_cabecalhos.py antes, ou aponte com --dic.")
    with open(path, encoding="utf-8", newline="") as fh:
        linhas = list(csv.DictReader(fh))
    faltando = {"base", "ano_de", "ano_ate", "posicao", "nome_canonico",
                "tipo", "separador", "decimal", "aspas", "nulos",
                "encoding"} - set(linhas[0].keys())
    if faltando:
        sys.exit(f"ERRO: o dicionário {path} não tem as colunas {sorted(faltando)}.\n"
                 f"Ele precisa ser a versão gerada a partir do cabecalhos.csv.")
    grupos: dict = {}
    for r in linhas:
        grupos.setdefault((r["base"], r["ano_de"], r["ano_ate"]), []).append(r)
    return [Esquema(b, d, a, v) for (b, d, a), v in grupos.items()]


def escolher_esquema(esquemas, base, ano) -> Esquema | None:
    ano = int(ano) if str(ano).isdigit() else 0
    for e in esquemas:
        if e.base == base and e.ano_de <= ano <= e.ano_ate:
            return e
    return None


# ===========================================================================
# Descompressão
# ===========================================================================

class PararLeitura(Exception):
    pass


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
        achado = shutil.which(c) if os.sep not in c else (c if Path(c).exists() else None)
        if achado:
            return achado
    return None


def capacidades():
    """(tem_binario_7z, py7zr_faz_streaming)."""
    b = achar_7z()
    try:
        import py7zr  # noqa: F401
        try:
            import py7zr.io  # noqa: F401
            stream = True
        except ImportError:
            stream = False
    except ImportError:
        stream = None
    return b, stream


def listar_internos(arquivo: Path, bin7z: str | None) -> list[tuple[str, int]]:
    if arquivo.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(arquivo) as z:
            return [(i.filename, i.file_size) for i in z.infolist()
                    if not i.is_dir()
                    and Path(i.filename).suffix.lower() in EXT_DADOS]
    import py7zr
    with py7zr.SevenZipFile(arquivo, "r") as z:
        return [(i.filename, int(i.uncompressed or 0)) for i in z.list()
                if not getattr(i, "is_directory", False)
                and Path(i.filename).suffix.lower() in EXT_DADOS]


class FonteBytes:
    """Entrega um objeto binário legível com o conteúdo já em UTF-8.

    Três caminhos, na ordem de preferência:
      1. binário do 7-Zip: descomprime para um pipe (mais rápido)
      2. py7zr >= 1.0    : WriterFactory escreve direto no pipe
      3. py7zr < 1.0     : extrai para arquivo temporário e lê de lá

    O transcode cp1252->UTF-8 acontece em blocos, porque o pyarrow.csv não
    aceita parâmetro de encoding e morre no primeiro "ç".
    """

    def __init__(self, arquivo: Path, interno: str, encoding: str,
                 bin7z: str | None, modo_py7zr: bool | None, tmp: str | None):
        self.arquivo, self.interno = arquivo, interno
        self.encoding = encoding
        self.bin7z, self.modo_py7zr, self.tmp = bin7z, modo_py7zr, tmp
        self.tmpdir = None
        self.proc = None
        self.thread = None
        self.erro = []
        self.lidos = 0

    def __enter__(self):
        if self.arquivo.suffix.lower() == ".zip":
            return self._por_zip()
        if self.bin7z:
            return self._por_binario()
        if self.modo_py7zr:
            return self._por_factory()
        return self._por_temporario()

    def __exit__(self, *exc):
        if self.proc is not None:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
            self.proc.kill()
            self.proc.wait()
        if self.thread is not None:
            self.thread.join(timeout=30)
        if self.tmpdir:
            for _ in range(10):
                shutil.rmtree(self.tmpdir, ignore_errors=True)
                if not Path(self.tmpdir).exists():
                    break
                time.sleep(0.2)
        if self.erro:
            raise self.erro[0]
        return False

    # -- transcode ---------------------------------------------------------
    def _envolver(self, bruto):
        """Embrulha um fluxo cp1252 num objeto de arquivo que entrega UTF-8.

        Precisa ser um io.RawIOBase de verdade: o pyarrow.csv checa
        `closed` e `readable()` antes de ler, e um objeto que só tenha
        `read()` não serve.
        """
        enc = self.encoding
        if enc.lower().replace("-", "") in ("utf8", "utf8sig"):
            return bruto            # já é UTF-8: nada a fazer
        import io
        pai = self

        class Transcodificador(io.RawIOBase):
            def __init__(self):
                super().__init__()
                self._dec = codecs.getincrementaldecoder(enc)(errors="replace")
                self._resto = b""

            def readable(self):
                return True

            def readinto(self, alvo):
                while not self._resto:
                    pedaco = bruto.read(BLOCO)
                    if not pedaco:
                        return 0
                    pai.lidos += len(pedaco)
                    self._resto = self._dec.decode(pedaco).encode("utf-8")
                saida = self._resto[:len(alvo)]
                self._resto = self._resto[len(saida):]
                alvo[:len(saida)] = saida
                return len(saida)

            def close(self):
                try:
                    bruto.close()
                except Exception:
                    pass
                super().close()

        return io.BufferedReader(Transcodificador(), buffer_size=BLOCO)

    def _por_zip(self):
        import zipfile
        self._zf = zipfile.ZipFile(self.arquivo)
        return self._envolver(self._zf.open(self.interno))

    def _por_binario(self):
        self.proc = subprocess.Popen(
            [self.bin7z, "e", "-so", "-bso0", "-bse0",
             str(self.arquivo), self.interno],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=BLOCO)
        return self._envolver(self.proc.stdout)

    def _por_factory(self):
        import py7zr
        from py7zr.io import Py7zIO, WriterFactory

        r_fd, w_fd = os.pipe()
        enc = self.encoding
        precisa = enc.lower().replace("-", "") not in ("utf8", "utf8sig")
        dec = codecs.getincrementaldecoder(enc)(errors="replace") if precisa else None
        pai = self

        class Cano(Py7zIO):
            def write(self, s):
                b = bytes(s)
                pai.lidos += len(b)
                os.write(w_fd, dec.decode(b).encode("utf-8") if precisa else b)
                return len(s)

            def read(self, size=None):
                return b""

            def seek(self, o, w=0):
                return 0

            def flush(self):
                return None

            def size(self):
                return pai.lidos

            def close(self):
                return None

        class Fabrica(WriterFactory):
            def create(self, filename):
                return Cano()

        def trabalhar():
            try:
                with py7zr.SevenZipFile(self.arquivo, "r") as z:
                    z.extract(targets=[self.interno], factory=Fabrica())
            except BrokenPipeError:
                pass
            except Exception as e:          # noqa: BLE001
                self.erro.append(e)
            finally:
                try:
                    os.close(w_fd)
                except OSError:
                    pass

        self.thread = threading.Thread(target=trabalhar, daemon=True)
        self.thread.start()
        return os.fdopen(r_fd, "rb", BLOCO)   # já vem em UTF-8

    def _por_temporario(self):
        import py7zr
        self.tmpdir = tempfile.mkdtemp(prefix="pdet_conv_", dir=self.tmp)
        with py7zr.SevenZipFile(self.arquivo, "r") as z:
            z.extract(path=self.tmpdir, targets=[self.interno])
        alvo = Path(self.tmpdir).joinpath(*self.interno.replace("\\", "/").split("/"))
        if not alvo.exists():
            achados = [q for q in Path(self.tmpdir).rglob("*") if q.is_file()]
            if not achados:
                raise RuntimeError("a extração não produziu arquivo")
            alvo = achados[0]
        return self._envolver(open(alvo, "rb", BLOCO))


# ===========================================================================
# SQL de conversão
# ===========================================================================

def expressao(col: str, tipo: str, esq: Esquema) -> str:
    """Texto cru -> valor tipado. Trata espaço de preenchimento, zeros à
    esquerda, os vários marcadores de ausente e o decimal do ano."""
    bruto = f'trim("{col}")'
    if esq.nulos:
        lista = ", ".join("'" + n.replace("'", "''") + "'" for n in esq.nulos)
        bruto = f"nullif_multi({bruto}, [{lista}])"
    else:
        bruto = f"nullif({bruto}, '')"

    if tipo == "VARCHAR":
        return f"{bruto} AS {col}"
    if tipo == "DATE":
        return f"try_strptime({bruto}, '%d/%m/%Y')::DATE AS {col}"
    if tipo == "BOOLEAN":
        return f"({bruto} IN ('1', '01', 'S', 'SIM')) AS {col}"

    num = bruto
    if esq.decimal == ",":
        num = f"replace({num}, ',', '.')"
    # sobra de milhar em alguns anos; e '.00' sem parte inteira
    num = f"regexp_replace({num}, '^\\.', '0.')"
    return f"try_cast({num} AS {tipo}) AS {col}"


def montar_select(esq: Esquema, ano: int) -> str:
    partes = [expressao(c, t, esq) for c, t in zip(esq.colunas, esq.tipos)]
    partes.append(f"{ano}::SMALLINT AS ano")
    if "municipio" in esq.colunas:
        casos = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in COD_UF.items())
        partes.append(
            "CASE substr(lpad(trim(\"municipio\"), 6, '0'), 1, 2) "
            f"{casos} ELSE 'NI' END AS uf")
    elif "uf_cod" in esq.colunas:
        casos = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in COD_UF.items())
        partes.append(
            "CASE lpad(trim(\"uf_cod\"), 2, '0') "
            f"{casos} ELSE 'NI' END AS uf")
    else:
        partes.append("'NI' AS uf")
    return ",\n       ".join(partes)


def preparar_conexao(con, memoria_gb: float, threads: int, tmp: str | None):
    con.execute(f"SET memory_limit='{memoria_gb:.1f}GB'")
    con.execute(f"SET threads={threads}")
    con.execute("SET preserve_insertion_order=false")
    if tmp:
        con.execute(f"SET temp_directory='{tmp}'")
    # nullif com lista: mais legível que nullif aninhado 6 vezes
    con.execute("""
        CREATE OR REPLACE MACRO nullif_multi(v, lista) AS
            CASE WHEN v IS NULL OR v = '' OR list_contains(lista, v)
                 THEN NULL ELSE v END
    """)


# ===========================================================================
# Conversão de uma unidade
# ===========================================================================

def converter_unidade(tarefa: dict) -> dict:
    import duckdb
    import pyarrow.csv as pacsv

    t0 = time.time()
    arquivo = Path(tarefa["arquivo"])
    interno = tarefa["interno"]
    esq: Esquema = tarefa["esquema"]
    ano = int(tarefa["ano"])
    saida = Path(tarefa["saida"])
    estagio = Path(tarefa["estagio"]) / f"u_{uuid.uuid4().hex[:12]}"

    reg = {
        "chave": tarefa["chave"], "arquivo": str(arquivo),
        "arquivo_interno": interno, "base": esq.base, "ano": str(ano),
        "recorte": tarefa["recorte"], "esquema": esq.rotulo,
        "linhas": "", "bytes_lidos": "", "bytes_parquet": "",
        "particoes": "", "segundos": "",
        "convertido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "",
    }

    try:
        estagio.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        preparar_conexao(con, tarefa["memoria_gb"], tarefa["threads"],
                         tarefa["tmp"])

        fonte = FonteBytes(arquivo, interno, esq.encoding, tarefa["bin7z"],
                           tarefa["modo_py7zr"], tarefa["tmp"])
        with fonte as fluxo:
            leitor = pacsv.open_csv(
                fluxo,
                read_options=pacsv.ReadOptions(
                    block_size=16 << 20, skip_rows=1,
                    column_names=esq.colunas, encoding="utf8"),
                parse_options=pacsv.ParseOptions(
                    delimiter=esq.separador,
                    quote_char=esq.aspas if esq.aspas else False,
                    newlines_in_values=False),
                convert_options=pacsv.ConvertOptions(
                    column_types={c: "string" for c in esq.colunas},
                    strings_can_be_null=False),
            )
            con.register("entrada", leitor)
            sel = montar_select(esq, ano)
            # o token amarra cada parquet à unidade que o gerou. É o que
            # permite reprocessar um arquivo sem duplicar linhas: a saída
            # anterior daquela unidade é apagada, e só ela.
            token = tarefa["token"]
            con.execute(
                f"COPY (SELECT {sel} FROM entrada) TO '{estagio.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (ano, uf), "
                f"OVERWRITE_OR_IGNORE 1, FILENAME_PATTERN 'u{token}_{{uuid}}')")

        gerados = sorted(estagio.rglob("*.parquet"))
        if not gerados:
            raise RuntimeError("nenhum parquet gerado (arquivo vazio?)")

        n = con.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [[q.as_posix() for q in gerados]]).fetchone()[0]

        raiz_base = saida / esq.base.lower()
        for antigo in raiz_base.rglob(f"u{token}_*.parquet"):
            antigo.unlink()

        # move para a árvore final só depois de tudo pronto
        bytes_pq = 0
        for q in gerados:
            bytes_pq += q.stat().st_size
            mover(q, raiz_base / q.relative_to(estagio))

        reg.update(linhas=str(n), bytes_lidos=str(fonte.lidos),
                   bytes_parquet=str(bytes_pq), particoes=str(len(gerados)),
                   segundos=f"{time.time() - t0:.1f}", status="ok")
        con.close()
    except Exception as e:                                  # noqa: BLE001
        reg["status"] = f"erro: {type(e).__name__}: {str(e)[:200]}"
        reg["segundos"] = f"{time.time() - t0:.1f}"
        reg["_traceback"] = traceback.format_exc()
    finally:
        shutil.rmtree(estagio, ignore_errors=True)
    return reg


# ===========================================================================
# Manifesto
# ===========================================================================

def ler_manifesto(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["chave"]: r for r in csv.DictReader(fh)}


def gravar_manifesto(path: Path, regs: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFESTO_CAMPOS,
                           extrasaction="ignore")
        w.writeheader()
        for r in sorted(regs.values(), key=lambda x: x["chave"]):
            w.writerow(r)
    os.replace(tmp, path)


def mesmo_volume(a: Path, b: Path) -> bool:
    """Descobre se dois caminhos estão no mesmo disco, sem exigir que
    existam ainda."""
    def existente(p: Path) -> Path:
        p = p.resolve()
        while not p.exists() and p.parent != p:
            p = p.parent
        return p
    ea, eb = existente(a), existente(b)
    if os.name == "nt":
        return str(ea)[:2].upper() == str(eb)[:2].upper()
    try:
        return os.stat(ea).st_dev == os.stat(eb).st_dev
    except OSError:
        return False


def livre(p: Path) -> int:
    q = p.resolve()
    while not q.exists() and q.parent != q:
        q = q.parent
    return shutil.disk_usage(q).free


def mover(origem: Path, destino: Path) -> None:
    """os.replace é atômico, mas só funciona dentro do mesmo volume. Entre
    discos (estágio no SSD -> Parquet no HD externo) ele levanta OSError e
    aí a cópia tem que ser explícita."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(origem, destino)
    except OSError:
        provisorio = destino.with_suffix(destino.suffix + ".parcial")
        shutil.copy2(origem, provisorio)   # cópia sequencial: o USB gosta
        os.replace(provisorio, destino)    # renomear no destino é atômico
        origem.unlink(missing_ok=True)


def fmt(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.1f} {u}".replace(".", ",")
        n /= 1024
    return f"{n} B"


# ===========================================================================
# Principal
# ===========================================================================

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", required=True, help="pasta com os .7z baixados")
    p.add_argument("--saida", required=True, help="raiz do Parquet (HD externo)")
    p.add_argument("--dic", default="dic_rais.csv")
    p.add_argument("--manifesto", default="",
                   help="padrão: <saida>/../03_meta/conversao.csv")
    p.add_argument("--tmp", default="",
                   help="pasta temporária: SSD interna, nunca OneDrive/rede")
    p.add_argument("--estagio", default="",
                   help="onde o Parquet é montado antes de ir para --saida. "
                        "Padrão: dentro de --tmp, ou o temporário do sistema. "
                        "Deve ficar no disco LOCAL, não no HD externo.")
    p.add_argument("--reserva-gb", type=float, default=20.0,
                   help="espaço livre mínimo exigido no estágio e na saída")
    p.add_argument("--base", action="append", default=[],
                   help="ex.: --base RAIS_VINCULOS (repetível)")
    p.add_argument("--ano", action="append", default=[])
    p.add_argument("--recorte", action="append", default=[])
    p.add_argument("--paralelo", type=int, default=1,
                   help="unidades simultâneas (3 costuma ser o ponto ideal)")
    p.add_argument("--memoria", type=float, default=9.0,
                   help="GB de RAM no total, dividido entre os processos")
    p.add_argument("--threads", type=int, default=0,
                   help="threads do DuckDB por processo (0 = automático)")
    p.add_argument("--ate-hora", default="", metavar="HH:MM",
                   help="para de iniciar novas unidades depois deste horário")
    p.add_argument("--ordem", choices=["menor", "maior", "ano"],
                   default="menor",
                   help="menor primeiro entrega anos utilizáveis mais cedo")
    p.add_argument("--refazer", action="store_true",
                   help="reprocessa mesmo o que já está no manifesto")
    p.add_argument("--incluir-parcial", action="store_true",
                   help="converte também as pastas 'AAAA Parcial'. Fora por "
                        "padrão: são divulgação antecipada e incompleta.")
    p.add_argument("--incluir-legado", action="store_true",
                   help="converte também as pastas 'Legado'. Fora por padrão: "
                        "duplicariam o ano.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--bin7z", default="")
    a = p.parse_args()

    raiz, saida = Path(a.raw), Path(a.saida)
    if not raiz.exists():
        sys.exit(f"ERRO: {raiz} não existe.")
    saida.mkdir(parents=True, exist_ok=True)

    # O estágio fica no disco LOCAL, nunca no HD externo. Gravar Parquet
    # direto no USB é onde a conversão trava: o DuckDB escreve em rajadas,
    # o barramento não acompanha, e as páginas sujas se acumulam na RAM até
    # o processo engasgar. Convertendo local e movendo depois, o USB só vê
    # uma cópia sequencial de arquivo pronto — que é o que ele faz bem.
    estagio = Path(a.estagio) if a.estagio else (
        Path(a.tmp) / "pdet_estagio" if a.tmp
        else Path(tempfile.gettempdir()) / "pdet_estagio")
    try:
        estagio.mkdir(parents=True, exist_ok=True)
        (estagio / ".escrita_ok").write_text("1", encoding="utf-8")
        (estagio / ".escrita_ok").unlink()
    except OSError as e:
        sys.exit(f"ERRO: não consigo escrever no estágio {estagio}: {e}\n"
                 f"Aponte outra pasta com --estagio (disco interno, fora de "
                 f"OneDrive e de unidade de rede).")
    for q in estagio.glob("u_*"):          # sobras de execução interrompida
        shutil.rmtree(q, ignore_errors=True)

    if mesmo_volume(estagio, saida):
        print("AVISO: o estágio está no mesmo volume da saída. Se --saida for "
              "o HD\n       externo, use --estagio para apontar o disco "
              "interno.")

    manifesto_path = (Path(a.manifesto) if a.manifesto
                      else saida.parent / "03_meta" / "conversao.csv")
    esquemas = carregar_esquemas(Path(a.dic))
    bin7z = achar_7z(a.bin7z or None)
    _, streaming = capacidades()
    if streaming is None and not bin7z:
        sys.exit("ERRO: preciso de py7zr ou do binário do 7-Zip.\n"
                 "  pip install py7zr")

    print(f"Dicionário   : {a.dic} ({len(esquemas)} esquemas)")
    if bin7z:
        print(f"Descompressão: 7-Zip ({bin7z}) — streaming")
    elif streaming:
        print("Descompressão: py7zr >= 1.0 — streaming, sem tocar o disco")
    else:
        print("Descompressão: py7zr < 1.0 — SEM streaming.")
        print("               Cada arquivo será extraído para a pasta "
              "temporária antes")
        print("               de converter, e apagado em seguida. Funciona, "
              "mas exige")
        print("               espaço livre igual ao maior .txt (o de SP passa "
              "de 50 GB).")
        print("               'pip install -U py7zr' elimina essa etapa.")
        if not a.tmp:
            print("               Use --tmp para escolher onde: o %TEMP% "
                  "padrão pode estar")
            print("               no OneDrive.")

    # --- monta a lista de unidades ------------------------------------
    # O "._" exclui os AppleDouble que o macOS cria em exFAT/FAT: eles casam
    # com *.7z, mas sao sidecars de metadados de 4 KB, nao arquivos de dados.
    arquivos = sorted(q for q in raiz.rglob("*")
                      if q.suffix.lower() in (".7z", ".zip")
                      and not q.name.startswith("._"))
    tarefas, ignorados = [], []
    for arq in arquivos:
        motivo = excluir_por_pasta(str(arq), a.incluir_parcial, a.incluir_legado)
        if motivo:
            ignorados.append((arq.name, motivo))
            continue
        ano, recorte, base = meta_do_caminho(arq)
        if a.base and base not in a.base:
            continue
        if a.ano and ano not in a.ano:
            continue
        if a.recorte and recorte not in a.recorte:
            continue
        esq = escolher_esquema(esquemas, base, ano)
        if esq is None:
            ignorados.append((arq.name, f"sem esquema para {base} {ano}"))
            continue
        try:
            internos = listar_internos(arq, bin7z)
        except Exception as e:                              # noqa: BLE001
            ignorados.append((arq.name, f"não consegui listar: {e}"))
            continue
        for interno, tam in internos:
            chave = f"{arq}::{interno}"
            tarefas.append({
                "chave": chave, "arquivo": str(arq),
                "token": hashlib.sha1(chave.encode("utf-8")).hexdigest()[:10],
                "interno": interno, "tamanho": tam, "esquema": esq,
                "ano": ano, "recorte": recorte,
            })

    manifesto = ler_manifesto(manifesto_path)
    if not a.refazer:
        pendentes = [t for t in tarefas
                     if manifesto.get(t["chave"], {}).get("status") != "ok"]
    else:
        pendentes = tarefas

    if a.ordem == "menor":
        pendentes.sort(key=lambda t: t["tamanho"])
    elif a.ordem == "maior":
        pendentes.sort(key=lambda t: -t["tamanho"])
    else:
        pendentes.sort(key=lambda t: (t["ano"], t["tamanho"]))

    total = sum(t["tamanho"] for t in pendentes)
    print(f"Unidades     : {len(tarefas)} no total, {len(pendentes)} pendentes"
          f" (~{fmt(total)} descomprimidos)")
    if ignorados:
        print(f"Ignorados    : {len(ignorados)}")
        por_motivo: dict = {}
        for nome, motivo in ignorados:
            por_motivo.setdefault(motivo, []).append(nome)
        for motivo, nomes in sorted(por_motivo.items(),
                                    key=lambda x: -len(x[1])):
            print(f"   {len(nomes):4d}  {motivo}")
            for nome in nomes[:3]:
                print(f"         - {nome}")
            if len(nomes) > 3:
                print(f"         ... (+{len(nomes) - 3})")

    if a.dry_run:
        for t in pendentes[:40]:
            print(f"  CONVERTERIA [{t['esquema'].rotulo}] {t['ano']} "
                  f"{t['recorte'] or '-'} {Path(t['arquivo']).name}"
                  f"::{t['interno']} ({fmt(t['tamanho'])})")
        if len(pendentes) > 40:
            print(f"  ... (+{len(pendentes) - 40})")
        return
    if not pendentes:
        print("Nada a fazer — tudo já convertido.")
        return

    limite = None
    if a.ate_hora:
        try:
            hh, mm = (int(x) for x in a.ate_hora.split(":"))
        except ValueError:
            sys.exit("ERRO: --ate-hora precisa do formato HH:MM.")
        agora = datetime.now()
        limite = agora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if limite <= agora:
            sys.exit(f"ERRO: {a.ate_hora} já passou. Escolha um horário à frente.")
        print(f"Limite       : {limite:%H:%M} — nenhuma unidade nova começa "
              f"depois disso")

    # espaço: o estágio precisa caber o maior Parquet de uma leva
    reserva = int(a.reserva_gb * 1024 ** 3)
    maior = max((t["tamanho"] for t in pendentes), default=0)
    precisa_estagio = int(maior * 0.25) * max(1, a.paralelo) + reserva
    if livre(estagio) < precisa_estagio:
        sys.exit(f"ERRO: pouco espaço no estágio {estagio}.\n"
                 f"  livre {fmt(livre(estagio))}, preciso de ~"
                 f"{fmt(precisa_estagio)}.\n"
                 f"  Reduza --paralelo, aponte outro --estagio, ou baixe "
                 f"--reserva-gb.")
    if livre(saida) < reserva:
        sys.exit(f"ERRO: pouco espaço em {saida}: {fmt(livre(saida))} livres.")
    print(f"Estágio      : {estagio} ({fmt(livre(estagio))} livres)")
    print(f"Saída        : {saida} ({fmt(livre(saida))} livres)")

    n_proc = max(1, a.paralelo)
    threads = a.threads or max(1, (os.cpu_count() or 4) // n_proc)
    mem = max(1.0, a.memoria / n_proc)
    print(f"Paralelismo  : {n_proc} processo(s), {threads} thread(s) e "
          f"{mem:.1f} GB cada\n")

    comuns = {
        "saida": str(saida), "estagio": str(estagio), "tmp": a.tmp or None,
        "bin7z": bin7z, "modo_py7zr": streaming, "memoria_gb": mem,
        "threads": threads,
    }

    feitos = erros = 0
    linhas_tot = bytes_tot = 0
    t0 = time.time()
    interrompido = parou_por_hora = False

    def registrar(reg):
        nonlocal feitos, erros, linhas_tot, bytes_tot
        manifesto[reg["chave"]] = reg
        gravar_manifesto(manifesto_path, manifesto)     # checkpoint por unidade
        nome = Path(reg["arquivo"]).name
        if reg["status"] == "ok":
            feitos += 1
            linhas_tot += int(reg["linhas"] or 0)
            bytes_tot += int(reg["bytes_parquet"] or 0)
            print(f"  ok  {nome}::{reg['arquivo_interno']} — "
                  f"{int(reg['linhas'] or 0):,} linhas, "
                  f"{fmt(int(reg['bytes_parquet'] or 0))}, "
                  f"{reg['particoes']} partições, {reg['segundos']}s"
                  .replace(",", "."))
        else:
            erros += 1
            print(f"  ERRO {nome}::{reg['arquivo_interno']} — {reg['status']}",
                  file=sys.stderr)

    try:
        if n_proc == 1:
            for i, t in enumerate(pendentes, 1):
                if limite and datetime.now() >= limite:
                    parou_por_hora = True
                    break
                print(f"[{i}/{len(pendentes)}] {t['ano']} "
                      f"{t['recorte'] or '-'} {Path(t['arquivo']).name}"
                      f"::{t['interno']} ({fmt(t['tamanho'])})")
                registrar(converter_unidade({**t, **comuns}))
        else:
            fila = list(pendentes)
            with ProcessPoolExecutor(max_workers=n_proc) as pool:
                vivos = {}
                while fila or vivos:
                    while (fila and len(vivos) < n_proc
                           and not (limite and datetime.now() >= limite)):
                        t = fila.pop(0)
                        vivos[pool.submit(converter_unidade,
                                          {**t, **comuns})] = t
                    if limite and datetime.now() >= limite and fila:
                        parou_por_hora = True
                        fila.clear()
                    if not vivos:
                        break
                    for fut in as_completed(list(vivos), timeout=None):
                        registrar(fut.result())
                        vivos.pop(fut, None)
                        break
    except KeyboardInterrupt:
        interrompido = True
        print("\nInterrompido. O manifesto está salvo — rode de novo para "
              "continuar de onde parou.", file=sys.stderr)
    finally:
        gravar_manifesto(manifesto_path, manifesto)
        # limpa só o que é nosso: --estagio pode ser uma pasta do usuário
        for q in estagio.glob("u_*"):
            shutil.rmtree(q, ignore_errors=True)
        try:
            if estagio.name == "pdet_estagio" and not any(estagio.iterdir()):
                estagio.rmdir()
        except OSError:
            pass

    dt = time.time() - t0
    restam = sum(1 for t in tarefas
                 if manifesto.get(t["chave"], {}).get("status") != "ok")
    print(f"\n{feitos} unidade(s) convertida(s), {erros} com erro, em "
          f"{dt / 60:.1f} min")
    print(f"{linhas_tot:,} linhas, {fmt(bytes_tot)} de Parquet"
          .replace(",", "."))
    print(f"Manifesto: {manifesto_path}")
    if parou_por_hora:
        print(f"\nParei no horário combinado. Faltam {restam} unidade(s) — "
              f"rode o mesmo comando amanhã.")
    elif restam and not interrompido:
        print(f"\nAinda faltam {restam} unidade(s). Veja os erros no manifesto.")
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
