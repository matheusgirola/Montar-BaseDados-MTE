#!/usr/bin/env bash
#
# Lançador macOS/Linux para o pipeline de microdados do PDET/MTE.
#
# Resolve o que é específico do Unix antes de chamar o Python:
# impedir suspensão da máquina, localizar o 7-Zip, conferir se o HD
# externo está montado, com espaço e num sistema de arquivos que
# aguenta arquivos grandes.
#
# Uso:
#   ./pdet.sh inventario
#   ./pdet.sh relatorio
#   ./pdet.sh baixar --base RAIS_VINCULOS --recorte NORDESTE --ano 2023 --ano 2024
#   ./pdet.sh baixar --base NOVO_CAGED --extrair
#   ./pdet.sh baixar --base RAIS_VINCULOS --ano 2015 --efemero
#
set -Eeuo pipefail

# >>> AJUSTE AQUI: raiz do projeto no HD externo <<<
# macOS: /Volumes/NOME_DO_DRIVE/pdet
# Linux: /media/$USER/NOME_DO_DRIVE/pdet  ou  /mnt/dados/pdet
DADOS="${PDET_DADOS:-/Volumes/HD E. 500GB/pdet}"

# Caminho do proprio script. Usa BASH_SOURCE quando existe (bash) e cai em
# $0 quando o script foi invocado por outro shell (ex.: `zsh pdet.sh`).
_ESTE="${BASH_SOURCE[0]:-$0}"

# Se nao estamos no bash, reexecuta no bash: o resto do script usa arrays e
# expansoes que o zsh interpreta de outro jeito.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$_ESTE" "$@"
fi

RAIZ="$(cd "$(dirname "$_ESTE")" && pwd)"
SO="$(uname -s)"

# cores só se for terminal interativo
if [[ -t 1 ]]; then
  AM=$'\033[33m'; CI=$'\033[36m'; VM=$'\033[31m'; CZ=$'\033[90m'; NC=$'\033[0m'
else
  AM=""; CI=""; VM=""; CZ=""; NC=""
fi
aviso() { echo "${AM}AVISO: $*${NC}" >&2; }
dica()  { echo "${CI}DICA: $*${NC}" >&2; }
erro()  { echo "${VM}ERRO: $*${NC}" >&2; exit 1; }
info()  { echo "${CZ}$*${NC}" >&2; }

# ---------------------------------------------------------------------------
# 1. Encoding — normalmente já é UTF-8, mas locale POSIX aparece em servidor
# ---------------------------------------------------------------------------
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [[ "${LANG:-}" != *UTF-8* && "${LC_ALL:-}" != *UTF-8* ]]; then
  export LC_ALL="${LC_ALL:-C.UTF-8}"
fi

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
# O ambiente do projeto vem primeiro: e ele que tem duckdb, py7zr e pyarrow.
# O python3 do PATH (Anaconda, /usr/bin) serve para o download, que so usa a
# biblioteca padrao, mas nao para converter nem montar o banco.
PY=""
for c in "$RAIZ/.venv/bin/python" "${VIRTUAL_ENV:-}/bin/python" python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done
[[ -n "$PY" ]] || erro "Python 3.8+ não encontrado.
  macOS: brew install python
  Debian/Ubuntu: sudo apt install python3"
info "Python       : $(command -v "$PY") ($("$PY" -V 2>&1))"

COMANDO="${1:-inventario}"; shift || true

# ---------------------------------------------------------------------------
# 3. HD externo: montado? formato? espaço?
# ---------------------------------------------------------------------------
checar_drive() {
  local ponto="$DADOS"
  while [[ ! -d "$ponto" && "$ponto" != "/" ]]; do ponto="$(dirname "$ponto")"; done

  if [[ "$SO" == "Darwin" ]]; then
    # No macOS o drive some de /Volumes quando é ejetado — falha cedo e claro
    if [[ "$DADOS" == /Volumes/* ]]; then
      local vol; vol="$(echo "$DADOS" | cut -d/ -f1-3)"
      [[ -d "$vol" ]] || erro "Drive não montado em $vol. Conecte o HD externo."
    fi
    # diskutil so aceita ponto de montagem ou device, nunca um subdiretorio:
    # descobre o device via df (campo 1 nunca tem espaco) e pergunta a ele.
    local dev; dev="$(df -P "$ponto" 2>/dev/null | awk 'NR==2{print $1}')" || dev=""
    local fs; fs="$(diskutil info "${dev:-$ponto}" 2>/dev/null | awk -F': *' '/Type \(Bundle\)/{print $2; exit}')" || fs=""
    local livre; livre="$(df -h "$ponto" | awk 'NR==2{print $4}')"
    info "Drive        : ${fs:-desconhecido} — $livre livres em $ponto"
    case "$fs" in
      msdos)  erro "FAT32 não aceita arquivos acima de 4 GB e os .txt da RAIS passam disso. Reformate como exFAT ou APFS." ;;
      exfat)  aviso "exFAT não tem journaling: queda de energia durante a gravação pode corromper a pasta." ;;
      ntfs)   aviso "NTFS no macOS costuma ser somente-leitura sem driver de terceiros. Teste a escrita antes do backfill." ;;
    esac
  else
    local fs; fs="$(df -PT "$ponto" 2>/dev/null | awk 'NR==2{print $2}')"
    local livre; livre="$(df -Ph "$ponto" | awk 'NR==2{print $4}')"
    info "Drive        : ${fs:-desconhecido} — $livre livres em $ponto"
    case "$fs" in
      vfat|msdos) erro "FAT32 não aceita arquivos acima de 4 GB e os .txt da RAIS passam disso. Reformate como ext4 ou exFAT." ;;
      exfat)      aviso "exFAT não tem journaling e é lento com muitos arquivos pequenos. ext4 é bem melhor se o drive só for usado no Linux." ;;
      fuseblk)    aviso "Drive montado via FUSE (provavelmente NTFS): a escrita será notavelmente mais lenta." ;;
    esac
  fi

  mkdir -p "$DADOS"
  [[ -w "$DADOS" ]] || erro "Sem permissão de escrita em $DADOS"
}

# ---------------------------------------------------------------------------
# 4. 7-Zip
# ---------------------------------------------------------------------------
checar_7z() {
  local z=""
  for c in 7z 7zz 7za 7zr /opt/homebrew/bin/7z /usr/local/bin/7z; do
    if command -v "$c" >/dev/null 2>&1; then z="$(command -v "$c")"; break; fi
  done
  if [[ -n "$z" ]]; then
    info "7-Zip        : $z"
  else
    aviso "7-Zip não encontrado — o Python usará py7zr (bem mais lento)."
    if [[ "$SO" == "Darwin" ]]; then
      dica "brew install sevenzip"
    else
      dica "sudo apt install p7zip-full   # ou: sudo dnf install p7zip p7zip-plugins"
    fi
    "$PY" -m pip install --user --quiet py7zr 2>/dev/null || true
  fi
}

# ---------------------------------------------------------------------------
# 5. Impedir suspensão durante downloads longos
# ---------------------------------------------------------------------------
# macOS: caffeinate. Linux: systemd-inhibit. Ausentes: segue sem.
sem_dormir() {
  if [[ "$SO" == "Darwin" ]] && command -v caffeinate >/dev/null 2>&1; then
    # -i não deixa o sistema dormir; -s também segura quando está na tomada
    caffeinate -i -s "$@"
  elif command -v systemd-inhibit >/dev/null 2>&1 \
       && [[ -d /run/systemd/system ]] \
       && systemd-inhibit --list >/dev/null 2>&1; then
    # o teste acima evita quebrar em container/WSL, onde o binário existe
    # mas não há barramento do systemd para conversar
    systemd-inhibit --what=idle:sleep --who=pdet \
      --why="download de microdados do PDET" -- "$@"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# 6. Executa
# ---------------------------------------------------------------------------
cd "$RAIZ"
ARGS=()

case "$COMANDO" in
  inventario)
    ARGS=("$PY" pdet_inventario.py crawl "$@")
    [[ " $* " == *" --resume "* ]] || ARGS+=(--force)
    ;;
  relatorio)
    ARGS=("$PY" pdet_inventario.py report "$@")
    ;;
  baixar)
    checar_drive
    # traduz --efemero para os dois flags do Python
    PASS=(); EXTRAIR=0
    for a in "$@"; do
      case "$a" in
        --efemero) PASS+=(--extrair --apagar-apos-extrair); EXTRAIR=1 ;;
        --extrair) PASS+=(--extrair); EXTRAIR=1 ;;
        *)         PASS+=("$a") ;;
      esac
    done
    (( EXTRAIR )) && checar_7z
    ARGS=("$PY" pdet_download.py --dados "$DADOS")
    (( ${#PASS[@]} )) && ARGS+=("${PASS[@]}")
    ;;
  *)
    erro "comando desconhecido: $COMANDO (use: inventario | relatorio | baixar)"
    ;;
esac

echo >&2
sem_dormir "${ARGS[@]}"
