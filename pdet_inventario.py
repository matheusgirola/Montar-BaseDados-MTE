#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 0 - Inventário do FTP de microdados do PDET/MTE
=====================================================

Objetivo: descobrir O QUE existe e QUANTO pesa no FTP, SEM baixar nenhum
microdado. A saída é um CSV com um registro por arquivo e um relatório
que responde: quantos GB por base, por ano, por UF/região.

Só depois disso você decide o escopo da base local (Fase 1+).

Uso:
    # 1) varre o FTP e grava o inventário (pode levar alguns minutos)
    python3 pdet_inventario.py crawl

    # se cair no meio (acontece), continue de onde parou:
    python3 pdet_inventario.py crawl --resume

    # 2) gera o relatório a partir do CSV
    python3 pdet_inventario.py report

Dependências: apenas a biblioteca padrão do Python 3.8+.
"""

from __future__ import annotations

import argparse
import csv
import ftplib
import json
import os
import re
import socket
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

HOST = "ftp.mtps.gov.br"
ROOT = "/pdet/microdados"

CSV_SAIDA = "inventario_ftp.csv"
STATE_JSON = "inventario_state.json"   # permite --resume
RELATORIO_MD = "relatorio_fase0.md"

TIMEOUT = 60          # segundos por operação de socket
MAX_TENTATIVAS = 4    # reconexões antes de desistir de um diretório

# Pausa entre listagens de diretório. Não é frescura: o FTP do PDET tem
# proteção anti-flood, e uma varredura sem pausa (centenas de comandos em
# segundos) pode fazer o servidor banir o IP temporariamente. Em rede
# corporativa o IP é compartilhado, então o bloqueio pega o escritório
# inteiro. 0,4s por diretório custa poucos minutos no total.
PAUSA_PADRAO = 0.4

# Se o servidor recusar a conexão logo de cara várias vezes seguidas,
# provavelmente é bloqueio temporário: esperar mais ajuda, insistir piora.
ESPERA_BLOQUEIO = 300

# Fatores de estimativa. São CHUTES iniciais deliberadamente conservadores;
# a Fase 1 substitui isso por medição real (baixe 1 arquivo, meça, ajuste).
FATOR_DESCOMPACTA = 10.0   # .7z/.zip -> .txt   (texto delimitado comprime muito)
FATOR_PARQUET = 1.6        # .7z      -> .parquet zstd com todas as colunas

CSV_CAMPOS = [
    "caminho", "diretorio", "arquivo", "extensao",
    "bytes", "modificado_em", "base", "ano", "mes", "recorte", "fonte_meta",
]


# --------------------------------------------------------------------------
# Classificação de caminhos
# --------------------------------------------------------------------------
# Heurísticas baseadas na estrutura conhecida do FTP. Se a estrutura mudar,
# o arquivo NÃO é descartado: cai em base="NAO_CLASSIFICADO" e aparece
# destacado no relatório para você ajustar as regras.

RE_ANO = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")
RE_COMPETENCIA = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(?!\d)")

REGRAS_BASE = [
    # (nome_da_base, regex aplicada ao caminho inteiro em MAIÚSCULAS)
    ("NOVO_CAGED_MOV",   re.compile(r"CAGEDMOV")),
    ("NOVO_CAGED_FOR",   re.compile(r"CAGEDFOR")),
    ("NOVO_CAGED_EXC",   re.compile(r"CAGEDEXC")),
    ("NOVO_CAGED_OUTRO", re.compile(r"NOVO[ _]?CAGED")),
    ("RAIS_VINCULOS",    re.compile(r"RAIS[_ ]?VINC")),
    ("RAIS_ESTAB",       re.compile(r"RAIS[_ ]?ESTAB")),
    ("RAIS_OUTRO",       re.compile(r"(?:^|/)RAIS")),
    ("CAGED_ANTIGO",     re.compile(r"CAGED")),
]

REGRAS_AUXILIAR = re.compile(
    r"(LAYOUT|DICION|LEIA|README|MANUAL|NOTA|ESTRUT|\.PDF$|\.DOC|\.XLS)"
)

# Recortes geográficos usados nos arquivos da RAIS.
RECORTES_RAIS = [
    "CENTRO_OESTE", "MG_ES_RJ", "NORDESTE", "NORTE", "SUL", "SP",
]
UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
]


def classificar(caminho: str) -> dict:
    """Extrai metadados de um caminho do FTP. Nunca levanta exceção."""
    alvo = caminho.upper().replace("\\", "/")
    nome = alvo.rsplit("/", 1)[-1]

    if REGRAS_AUXILIAR.search(alvo):
        base = "AUXILIAR_DOC"
    else:
        base = "NAO_CLASSIFICADO"
        for nome_base, regex in REGRAS_BASE:
            if regex.search(alvo):
                base = nome_base
                break

    # ano/mês: a competência (AAAAMM) tem prioridade sobre o ano solto
    ano = mes = ""
    m = RE_COMPETENCIA.search(nome)
    if m:
        ano, mes = m.group(1), m.group(2)
    else:
        anos = RE_ANO.findall(alvo)
        if anos:
            # o último ano do caminho costuma ser o mais específico
            ano = anos[-1]

    # recorte geográfico
    recorte = ""
    for r in RECORTES_RAIS:
        if r in nome:
            recorte = r
            break
    if not recorte:
        for uf in UFS:
            if re.search(rf"(?<![A-Z]){uf}(?![A-Z])", nome):
                recorte = uf
                break

    return {"base": base, "ano": ano, "mes": mes, "recorte": recorte}


# --------------------------------------------------------------------------
# Cliente FTP resiliente
# --------------------------------------------------------------------------

class ClienteFTP:
    """Wrapper com reconexão automática. FTP de órgão público cai; é normal."""

    def __init__(self, host: str, timeout: int = TIMEOUT, verbose: bool = True,
                 port: int = 21, user: str = "anonymous",
                 passwd: str = "pdet-inventario@example.org",
                 usar_mlsd: bool = True):
        self.host, self.port = host, port
        self.user, self.passwd = user, passwd
        self.timeout, self.verbose = timeout, verbose
        self.ftp: ftplib.FTP | None = None
        self.suporta_mlsd = usar_mlsd
        self.conectar()

    def log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    def conectar(self, tentativas: int = 3) -> None:
        """Conecta e faz login, com espera longa se a conexão for recusada."""
        ultimo = None
        for i in range(1, tentativas + 1):
            if self.ftp is not None:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            ftp = ftplib.FTP()
            # Nomes de pastas do PDET têm acento ("NOVO CAGED", etc). Muitos
            # servidores antigos respondem em latin-1; utf-8 quebraria a leitura.
            ftp.encoding = "latin-1"
            try:
                ftp.connect(self.host, self.port, timeout=self.timeout)
                ftp.login(self.user, self.passwd)
                ftp.set_pasv(True)
                try:
                    ftp.voidcmd("TYPE I")   # necessário para o comando SIZE
                except ftplib.all_errors:
                    pass
                self.ftp = ftp
                self.log(f"  [conectado a {self.host}:{self.port}]")
                return
            except ConnectionRefusedError as e:
                ultimo = e
                if i < tentativas:
                    self.log(
                        f"  [conexão RECUSADA pelo servidor. Isso normalmente "
                        f"significa que o FTP está fora do ar ou bloqueou seu IP "
                        f"temporariamente por excesso de acessos.\n"
                        f"   Aguardando {ESPERA_BLOQUEIO // 60} min "
                        f"({i}/{tentativas})...]")
                    time.sleep(ESPERA_BLOQUEIO)
            except (socket.timeout, socket.gaierror, ftplib.all_errors, OSError) as e:
                ultimo = e
                if i < tentativas:
                    espera = 10 * i
                    self.log(f"  [falha ao conectar: {e} — nova tentativa "
                             f"em {espera}s ({i}/{tentativas})]")
                    time.sleep(espera)

        raise ConnectionError(
            f"Não consegui conectar em {self.host}:{self.port} após "
            f"{tentativas} tentativas.\n"
            f"Último erro: {ultimo}\n\n"
            f"Para descobrir a causa, rode:  python diagnostico_ftp.py\n"
            f"  - se os FTPs de controle também falharem -> sua rede bloqueia a porta 21\n"
            f"  - se só o MTE falhar -> servidor fora do ar ou bloqueio temporário do seu IP\n"
            f"Se já rodou o inventário hoje, espere algumas horas e use\n"
            f"--pausa 1.5 para varrer mais devagar."
        ) from ultimo

    def listar(self, caminho: str) -> list[dict]:
        """Retorna [{'nome','tipo','bytes','modify'}] para um diretório."""
        ultimo_erro = None
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            try:
                if self.suporta_mlsd:
                    try:
                        return self._listar_mlsd(caminho)
                    except ftplib.error_perm as e:
                        # 500/502 = comando não implementado -> usa LIST
                        if str(e)[:3] in ("500", "501", "502", "504"):
                            self.suporta_mlsd = False
                            self.log("  [MLSD indisponível, usando LIST]")
                        else:
                            raise
                return self._listar_list(caminho)
            except (ftplib.error_temp, ftplib.error_proto, socket.error,
                    EOFError, OSError) as e:
                ultimo_erro = e
                # Recusa de conexão costuma ser bloqueio temporário por
                # excesso de requisições, não instabilidade de rede.
                # Nesse caso, insistir rápido só prolonga o bloqueio.
                if isinstance(e, ConnectionRefusedError):
                    espera = ESPERA_BLOQUEIO
                    self.log(f"  [conexão RECUSADA — provável bloqueio "
                             f"temporário por excesso de acessos. Aguardando "
                             f"{espera // 60} min antes de tentar de novo "
                             f"({tentativa}/{MAX_TENTATIVAS})]")
                else:
                    espera = 2 ** tentativa
                    self.log(f"  [erro em {caminho}: {e} — retry {tentativa}/"
                             f"{MAX_TENTATIVAS} em {espera}s]")
                time.sleep(espera)
                try:
                    self.conectar(tentativas=1)   # backoff já foi aplicado acima
                except Exception as e2:
                    ultimo_erro = e2
            except ftplib.error_perm as e:
                # 550 = sem permissão / não existe. Não adianta insistir.
                self.log(f"  [sem acesso a {caminho}: {e}]")
                return []
        raise RuntimeError(f"falha ao listar {caminho}: {ultimo_erro}")

    def _listar_mlsd(self, caminho: str) -> list[dict]:
        itens = []
        for nome, fatos in self.ftp.mlsd(caminho,
                                         facts=["type", "size", "modify"]):
            if nome in (".", ".."):
                continue
            tipo = fatos.get("type", "")
            if tipo in ("cdir", "pdir"):
                continue
            itens.append({
                "nome": nome,
                "tipo": "dir" if tipo == "dir" else "file",
                "bytes": int(fatos["size"]) if fatos.get("size", "").isdigit() else None,
                "modify": fatos.get("modify", ""),
                "fonte_meta": "MLSD",
            })
        return itens

    # Formatos de LIST: Unix e MS-DOS.
    RE_UNIX = re.compile(
        r"^([\-dl])\S*\s+\d+\s+\S+\s+\S+\s+(\d+)\s+"
        r"(\w{3}\s+\d+\s+(?:\d{4}|\d{2}:\d{2}))\s+(.+)$"
    )
    RE_DOS = re.compile(
        r"^(\d{2}-\d{2}-\d{2,4})\s+(\d{2}:\d{2}[AP]M)\s+(<DIR>|\d+)\s+(.+)$"
    )

    def _listar_list(self, caminho: str) -> list[dict]:
        linhas: list[str] = []
        self.ftp.retrlines(f"LIST {caminho}", linhas.append)
        itens = []
        for linha in linhas:
            m = self.RE_UNIX.match(linha)
            if m:
                flag, tam, data, nome = m.groups()
                if nome in (".", ".."):
                    continue
                itens.append({
                    "nome": nome.strip(),
                    "tipo": "dir" if flag == "d" else "file",
                    "bytes": int(tam) if flag != "d" else None,
                    "modify": data, "fonte_meta": "LIST",
                })
                continue
            m = self.RE_DOS.match(linha)
            if m:
                data, hora, tam, nome = m.groups()
                ehdir = tam == "<DIR>"
                itens.append({
                    "nome": nome.strip(),
                    "tipo": "dir" if ehdir else "file",
                    "bytes": None if ehdir else int(tam),
                    "modify": f"{data} {hora}", "fonte_meta": "LIST",
                })
        return itens

    def tamanho(self, caminho: str) -> int | None:
        try:
            return self.ftp.size(caminho)
        except ftplib.all_errors:
            return None

    def modificado(self, caminho: str) -> str:
        try:
            r = self.ftp.voidcmd(f"MDTM {caminho}")
            return r[4:].strip()
        except ftplib.all_errors:
            return ""

    def fechar(self) -> None:
        try:
            self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Varredura
# --------------------------------------------------------------------------

def crawl(args: argparse.Namespace) -> None:
    estado = {"fila": [args.root], "feitos": [], "n_arquivos": 0, "bytes": 0}
    modo = "w"

    if args.resume and os.path.exists(args.state):
        with open(args.state, encoding="utf-8") as fh:
            estado = json.load(fh)
        modo = "a"
        print(f"Retomando: {len(estado['feitos'])} diretórios já varridos, "
              f"{len(estado['fila'])} na fila.", file=sys.stderr)
    elif os.path.exists(args.csv) and not args.force:
        sys.exit(f"ERRO: {args.csv} já existe. Use --resume ou --force.")

    feitos = set(estado["feitos"])
    fila = list(estado["fila"])
    try:
        cli = ClienteFTP(args.host, timeout=args.timeout, port=args.port,
                         user=args.user, passwd=args.passwd,
                         usar_mlsd=not args.no_mlsd)
    except ConnectionError as e:
        # mensagem limpa em vez de traceback: o problema é de rede/servidor,
        # não um bug que o usuário precise depurar
        sys.exit(f"\n{e}\n")

    fh = open(args.csv, modo, newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=CSV_CAMPOS)
    if modo == "w":
        writer.writeheader()

    t0 = time.time()
    try:
        while fila:
            diretorio = fila.pop(0)
            if diretorio in feitos:
                continue

            profundidade = diretorio.count("/") - args.root.count("/")
            if args.max_depth and profundidade > args.max_depth:
                feitos.add(diretorio)
                continue

            print(f"[{len(feitos):4d}] {diretorio}", file=sys.stderr, flush=True)
            itens = cli.listar(diretorio)

            for item in itens:
                caminho = f"{diretorio.rstrip('/')}/{item['nome']}"
                if item["tipo"] == "dir":
                    if caminho not in feitos:
                        fila.append(caminho)
                    continue

                tam = item["bytes"]
                mod = item["modify"]
                fonte = item["fonte_meta"]
                # LIST não dá bytes exatos em alguns servidores: complementa
                if tam is None:
                    tam = cli.tamanho(caminho)
                    fonte = "SIZE"
                if not mod:
                    mod = cli.modificado(caminho)

                meta = classificar(caminho)
                writer.writerow({
                    "caminho": caminho,
                    "diretorio": diretorio,
                    "arquivo": item["nome"],
                    "extensao": os.path.splitext(item["nome"])[1].lower().lstrip("."),
                    "bytes": tam if tam is not None else "",
                    "modificado_em": mod,
                    "fonte_meta": fonte,
                    **meta,
                })
                estado["n_arquivos"] += 1
                estado["bytes"] += tam or 0

            fh.flush()
            feitos.add(diretorio)
            _salvar_estado(args.state, fila, feitos, estado)
            if args.pausa > 0:
                time.sleep(args.pausa)

            if args.limit and estado["n_arquivos"] >= args.limit:
                print("Limite de arquivos atingido (--limit).", file=sys.stderr)
                break
    except KeyboardInterrupt:
        print("\nInterrompido. Estado salvo — rode de novo com --resume.",
              file=sys.stderr)
    finally:
        fh.close()
        cli.fechar()
        _salvar_estado(args.state, fila, feitos, estado)

    dt = time.time() - t0
    print(f"\nOK: {estado['n_arquivos']} arquivos, "
          f"{fmt_bytes(estado['bytes'])}, em {dt:.0f}s -> {args.csv}",
          file=sys.stderr)


def _salvar_estado(path, fila, feitos, estado) -> None:
    estado["fila"] = fila
    estado["feitos"] = sorted(feitos)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(estado, fh, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Relatório
# --------------------------------------------------------------------------

def fmt_bytes(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unidade == "TB":
            return f"{n:,.1f} {unidade}".replace(",", "_").replace(".", ",").replace("_", ".")
        n /= 1024
    return f"{n} B"


def _tabela(linhas: list[list[str]], cabec: list[str]) -> str:
    larg = [max(len(str(c)), *(len(str(l[i])) for l in linhas)) if linhas
            else len(str(c)) for i, c in enumerate(cabec)]
    def linha(vals):
        return "| " + " | ".join(str(v).ljust(larg[i]) if i == 0
                                 else str(v).rjust(larg[i])
                                 for i, v in enumerate(vals)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in larg) + "|"
    return "\n".join([linha(cabec), sep] + [linha(l) for l in linhas])


def report(args: argparse.Namespace) -> None:
    if not os.path.exists(args.csv):
        sys.exit(f"ERRO: {args.csv} não encontrado. Rode 'crawl' primeiro.")

    with open(args.csv, encoding="utf-8") as fh:
        registros = list(csv.DictReader(fh))
    for r in registros:
        r["bytes"] = int(r["bytes"]) if r["bytes"].isdigit() else 0

    total_n = len(registros)
    total_b = sum(r["bytes"] for r in registros)
    sem_tam = sum(1 for r in registros if r["bytes"] == 0)

    out: list[str] = []
    W = out.append
    W(f"# Fase 0 — Inventário do FTP do PDET\n")
    W(f"- Origem: `ftp://{args.host}{args.root}`")
    W(f"- Gerado em: {datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M %Z}")
    W(f"- Arquivos: **{total_n:,}**".replace(",", "."))
    W(f"- Volume comprimido: **{fmt_bytes(total_b)}**")
    if sem_tam:
        W(f"- ⚠️ {sem_tam} arquivo(s) sem tamanho reportado pelo servidor "
          f"(subestimam o total)")
    W("")

    # --- por base -----------------------------------------------------
    por_base = defaultdict(lambda: [0, 0])
    for r in registros:
        por_base[r["base"]][0] += 1
        por_base[r["base"]][1] += r["bytes"]

    W("## Volume por base\n")
    linhas = []
    for base, (n, b) in sorted(por_base.items(), key=lambda x: -x[1][1]):
        linhas.append([
            base, f"{n:,}".replace(",", "."), fmt_bytes(b),
            fmt_bytes(b * args.fator_descompacta),
            fmt_bytes(b * args.fator_parquet),
            f"{100 * b / total_b:.1f}%".replace(".", ",") if total_b else "-",
        ])
    W(_tabela(linhas, ["base", "arqs", "comprimido",
                       "~descompactado", "~parquet", "%"]))
    W("")
    W(f"> Estimativas usam fatores {args.fator_descompacta}x (descompactação) "
      f"e {args.fator_parquet}x (parquet zstd, todas as colunas). "
      f"São chutes: meça 1 arquivo real na Fase 1 e recalibre com "
      f"`--fator-descompacta` / `--fator-parquet`.\n")

    # --- por ano ------------------------------------------------------
    por_ano = defaultdict(lambda: [0, 0])
    for r in registros:
        if r["ano"]:
            por_ano[r["ano"]][0] += 1
            por_ano[r["ano"]][1] += r["bytes"]

    if por_ano:
        W("## Volume por ano\n")
        linhas = [[ano, f"{n:,}".replace(",", "."), fmt_bytes(b),
                   fmt_bytes(b * args.fator_parquet)]
                  for ano, (n, b) in sorted(por_ano.items())]
        W(_tabela(linhas, ["ano", "arqs", "comprimido", "~parquet"]))
        W("")

        acum = 0
        anos_desc = sorted(por_ano.items(), reverse=True)
        W("**Custo de escopo — últimos N anos (em parquet):**\n")
        marcos = []
        for i, (ano, (_, b)) in enumerate(anos_desc, start=1):
            acum += b
            if i in (1, 3, 5, 10, 15, 20, len(anos_desc)):
                marcos.append([f"{i} ano(s) (até {ano})",
                               fmt_bytes(acum * args.fator_parquet)])
        W(_tabela(marcos, ["escopo", "~parquet acumulado"]))
        W("")

    # --- recorte geográfico (RAIS) ------------------------------------
    rais = [r for r in registros if r["base"].startswith("RAIS") and r["recorte"]]
    if rais:
        por_rec = defaultdict(lambda: [0, 0])
        for r in rais:
            por_rec[r["recorte"]][0] += 1
            por_rec[r["recorte"]][1] += r["bytes"]
        W("## RAIS por recorte geográfico\n")
        linhas = [[rec, f"{n:,}".replace(",", "."), fmt_bytes(b),
                   fmt_bytes(b * args.fator_parquet)]
                  for rec, (n, b) in sorted(por_rec.items(), key=lambda x: -x[1][1])]
        W(_tabela(linhas, ["recorte", "arqs", "comprimido", "~parquet"]))
        W("\n> Se o foco é PI/Nordeste, a linha NORDESTE é o seu escopo "
          "mínimo viável.\n")

    # --- extensões ----------------------------------------------------
    por_ext = defaultdict(lambda: [0, 0])
    for r in registros:
        por_ext[r["extensao"] or "(sem)"][0] += 1
        por_ext[r["extensao"] or "(sem)"][1] += r["bytes"]
    W("## Por extensão\n")
    W(_tabela([[e, f"{n:,}".replace(",", "."), fmt_bytes(b)]
               for e, (n, b) in sorted(por_ext.items(), key=lambda x: -x[1][1])],
              ["ext", "arqs", "bytes"]))
    W("")

    # --- não classificados --------------------------------------------
    nc = [r for r in registros if r["base"] == "NAO_CLASSIFICADO"]
    if nc:
        nc.sort(key=lambda r: -r["bytes"])
        W(f"## ⚠️ Não classificados ({len(nc)} arquivos, "
          f"{fmt_bytes(sum(r['bytes'] for r in nc))})\n")
        W("Ajuste `REGRAS_BASE` no script se algo relevante aparecer aqui.\n")
        for r in nc[:20]:
            W(f"- `{r['caminho']}` — {fmt_bytes(r['bytes'])}")
        if len(nc) > 20:
            W(f"- ... (+{len(nc) - 20})")
        W("")

    # --- decisões -----------------------------------------------------
    W("## Decisões que este inventário destrava\n")
    W("1. **Escopo temporal**: quantos anos de RAIS cabem no orçamento de disco?")
    W("2. **Escopo geográfico**: só NORDESTE ou Brasil inteiro?")
    W("3. **Colunas**: se o parquet completo já couber, não vale a pena "
      "montar versão *slim*.")
    W("4. **Ordem do backfill**: comece pelo ano mais recente e caminhe "
      "para trás.")
    W("5. **Tempo de download**: divida o volume pela sua banda real — é "
      "isso que define se o backfill leva 1 noite ou 1 semana.")

    texto = "\n".join(out)
    with open(args.saida, "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    print(texto)
    print(f"\n[relatório salvo em {args.saida}]", file=sys.stderr)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="varre o FTP e grava o inventário")
    c.add_argument("--host", default=HOST)
    c.add_argument("--port", type=int, default=21)
    c.add_argument("--user", default="anonymous")
    c.add_argument("--passwd", default="pdet-inventario@example.org")
    c.add_argument("--root", default=ROOT)
    c.add_argument("--csv", default=CSV_SAIDA)
    c.add_argument("--state", default=STATE_JSON)
    c.add_argument("--timeout", type=int, default=TIMEOUT)
    c.add_argument("--max-depth", type=int, default=0,
                   help="0 = sem limite; útil para uma sondagem rápida")
    c.add_argument("--limit", type=int, default=0,
                   help="para após N arquivos (teste)")
    c.add_argument("--pausa", type=float, default=PAUSA_PADRAO,
                   metavar="SEG",
                   help=f"pausa entre diretórios, em segundos "
                        f"(padrão {PAUSA_PADRAO}; use 0 para desligar, "
                        f"ou 1.0+ se o servidor estiver recusando conexões)")
    c.add_argument("--no-mlsd", action="store_true",
                   help="força o modo LIST (servidores antigos)")
    c.add_argument("--resume", action="store_true")
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=crawl)

    r = sub.add_parser("report", help="gera o relatório a partir do CSV")
    r.add_argument("--csv", default=CSV_SAIDA)
    r.add_argument("--saida", default=RELATORIO_MD)
    r.add_argument("--host", default=HOST)
    r.add_argument("--root", default=ROOT)
    r.add_argument("--fator-descompacta", type=float, default=FATOR_DESCOMPACTA)
    r.add_argument("--fator-parquet", type=float, default=FATOR_PARQUET)
    r.set_defaults(func=report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()