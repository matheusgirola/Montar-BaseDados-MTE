
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnostico_ftp.py — descobre POR QUE a conexão com o FTP do PDET falhou.

O erro "WinError 10061 / Connection refused" tem causas diferentes que pedem
soluções opostas. Este script separa uma da outra:

  A) O servidor do MTE está fora do ar  -> esperar e tentar de novo
  B) Sua rede bloqueia a porta 21       -> falar com TI, usar outra rede,
                                            ou trocar de fonte de dados
  C) Modo ativo/passivo mal negociado   -> ajuste no cliente

Uso:
    python diagnostico_ftp.py
    python diagnostico_ftp.py --insistir 20     # tenta 20x, de 30 em 30s
"""

import argparse
import socket
import ssl
import sys
import time

ALVO = ("ftp.mtps.gov.br", 21)

# Servidores FTP públicos e estáveis. Servem de "grupo de controle":
# se ELES também falharem, o problema é a sua rede, não o MTE.
CONTROLES_FTP = [
    ("ftp.gnu.org", 21),
    ("ftp.debian.org", 21),
]

# Se o 443 funciona mas o 21 não, o padrão é bloqueio de porta.
CONTROLES_HTTPS = [
    ("www.gov.br", 443),
]

OK, FALHA, AVISO = "[ OK ]", "[FALHA]", "[AVISO]"


def testa_tcp(host, porta, timeout=15):
    """Retorna (sucesso, descricao_curta, detalhe)."""
    try:
        infos = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, "DNS não resolveu", str(e)

    # de-duplica mantendo a família de endereço junto (IPv4 e IPv6)
    vistos, alvos = set(), []
    for familia, _, _, _, sa in infos:
        if sa[0] not in vistos:
            vistos.add(sa[0])
            alvos.append((familia, sa))

    erros = []
    for familia, sa in alvos:
        ip = sa[0]
        try:
            s = socket.socket(familia, socket.SOCK_STREAM)
        except OSError as e:
            # típico de máquina sem IPv6: pula em vez de quebrar
            erros.append(f"{ip}: família indisponível ({e.strerror or e})")
            continue
        s.settimeout(timeout)
        t0 = time.time()
        try:
            s.connect(sa)
            ms = (time.time() - t0) * 1000
            banner = ""
            if porta == 21:
                try:
                    s.settimeout(10)
                    banner = s.recv(256).decode("latin-1", "replace").strip()
                except OSError:
                    banner = "(sem banner)"
            s.close()
            return True, f"conectou em {ip} ({ms:.0f} ms)", banner
        except socket.timeout:
            erros.append(f"{ip}: timeout ({timeout}s) — pacotes descartados")
        except ConnectionRefusedError:
            erros.append(f"{ip}: recusada (RST) — nada escutando, ou bloqueio ativo")
        except OSError as e:
            erros.append(f"{ip}: {e}")
        finally:
            try:
                s.close()
            except OSError:
                pass
    return False, f"{len(alvos)} IP(s), nenhum conectou", "; ".join(erros)


def testa_ftp_completo(host, porta, timeout=25):
    """Login anônimo + listagem em modo passivo (o que o script usa de fato)."""
    import ftplib
    ftp = ftplib.FTP()
    ftp.encoding = "latin-1"
    try:
        ftp.connect(host, porta, timeout=timeout)
        ftp.login("anonymous", "diagnostico@example.org")
        ftp.set_pasv(True)
        itens = ftp.nlst("/pdet/microdados")
        ftp.quit()
        return True, f"login e listagem OK ({len(itens)} itens na raiz)", ""
    except Exception as e:
        try:
            ftp.close()
        except Exception:
            pass
        return False, type(e).__name__, str(e)[:200]


def testa_https(host, porta, timeout=15):
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, porta), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=host):
                return True, "handshake TLS OK", ""
    except Exception as e:
        return False, type(e).__name__, str(e)[:200]


def rodada(verboso=True):
    """Executa a bateria. Retorna True se o FTP do PDET respondeu."""
    linha = lambda: print("-" * 68)
    res = {}

    print("\n=== 1. Internet em geral (HTTPS/443) ===")
    for h, p in CONTROLES_HTTPS:
        ok, desc, det = testa_https(h, p)
        res["https"] = ok
        print(f"  {OK if ok else FALHA} {h}:{p} — {desc}")
        if det and not ok:
            print(f"         {det}")

    print("\n=== 2. Porta 21 sai da sua rede? (FTPs públicos de controle) ===")
    algum_controle = False
    for h, p in CONTROLES_FTP:
        ok, desc, det = testa_tcp(h, p)
        algum_controle = algum_controle or ok
        print(f"  {OK if ok else FALHA} {h}:{p} — {desc}")
        if det:
            print(f"         {det[:150]}")
    res["porta21"] = algum_controle

    print("\n=== 3. FTP do PDET/MTE ===")
    ok_tcp, desc, det = testa_tcp(*ALVO)
    print(f"  {OK if ok_tcp else FALHA} {ALVO[0]}:{ALVO[1]} — {desc}")
    if det:
        print(f"         {det[:200]}")
    res["pdet_tcp"] = ok_tcp

    if ok_tcp:
        ok_ftp, desc, det = testa_ftp_completo(*ALVO)
        print(f"  {OK if ok_ftp else FALHA} login anônimo + listagem — {desc}")
        if det:
            print(f"         {det}")
        res["pdet_ftp"] = ok_ftp
    else:
        res["pdet_ftp"] = False

    # ---------------- veredito ----------------
    print()
    linha()
    print("VEREDITO")
    linha()

    if res["pdet_ftp"]:
        print("  O FTP do PDET está funcionando agora.")
        print("  Rode o inventário:  .\\pdet-windows.ps1 inventario -Conda")
        return True

    if not res["https"]:
        print("  Sua máquina parece sem internet (ou atrás de proxy que exige")
        print("  autenticação). Resolva a conexão antes de tudo.")
        return False

    if not res["porta21"]:
        print("  CAUSA PROVÁVEL: sua rede bloqueia a porta 21 (FTP).")
        print("  Nenhum servidor FTP público respondeu, então não é o MTE.")
        print()
        print("  Isso é comum em rede corporativa. Opções:")
        print("    - testar em outra rede (celular via roteamento, rede de casa)")
        print("    - pedir à TI liberação de saída na porta 21 + portas passivas")
        print("    - usar as alternativas sem FTP (veja abaixo)")
        return False

    if not res["pdet_tcp"]:
        print("  CAUSA PROVÁVEL: o servidor do MTE está fora do ar.")
        print("  A porta 21 sai normalmente da sua rede (os controles passaram),")
        print("  mas o host do PDET recusou a conexão.")
        print()
        print("  Esse FTP cai com frequência e volta sozinho, às vezes em horas.")
        print("  Use:  python diagnostico_ftp.py --insistir 40")
        print("  para ele avisar assim que o serviço voltar.")
        return False

    print("  O TCP conecta, mas o login ou a listagem falham.")
    print("  Provável limite de conexões simultâneas no servidor (tente mais")
    print("  tarde) ou bloqueio das portas do modo passivo pelo firewall.")
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--insistir", type=int, default=0, metavar="N",
                   help="repete o teste N vezes, a cada 30s, até o FTP voltar")
    a = p.parse_args()

    print(f"Diagnóstico de conexão com {ALVO[0]}")
    print(f"Python {sys.version.split()[0]} | {time.strftime('%d/%m/%Y %H:%M:%S')}")

    if rodada():
        return 0

    for i in range(1, a.insistir + 1):
        print(f"\n{'=' * 68}")
        print(f"Aguardando 30s — tentativa {i}/{a.insistir} "
              f"({time.strftime('%H:%M:%S')})")
        time.sleep(30)
        if rodada():
            print("\n>>> O FTP VOLTOU. Rode o inventário agora.")
            return 0

    print("\n" + "-" * 68)
    print("ALTERNATIVAS SEM FTP")
    print("-" * 68)
    print("  1. As páginas de cada ano da RAIS no site do MTE às vezes trazem")
    print("     link do OneDrive com os mesmos arquivos, via HTTPS.")
    print("  2. Base dos Dados (BigQuery): RAIS e CAGED já tratados, consulta")
    print("     por SQL sem baixar nada. Tem defasagem na versão aberta.")
    print("  3. FileZilla: se ele conectar e o Python não, o problema é")
    print("     configuração local (firewall/antivírus filtrando o Python).")
    return 1


if __name__ == "__main__":
    sys.exit(main())