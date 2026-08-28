<#
.SYNOPSIS
    Prepara o ambiente Python do projeto PDET e deixa o 'uv' utilizavel,
    sem administrador e sem depender do PATH.

.DESCRIPTION
    ---------------------------------------------------------------------
    OS DOIS COMANDOS QUE FUNCIONAM, se voce so quer rodar e seguir a vida:

        & "$env:USERPROFILE\.local\bin\uv.exe" sync

        & "$env:USERPROFILE\.local\bin\uv.exe" run python pdet_parquet.py `
            --raw E:\pdet\00_raw --saida E:\pdet\10_parquet `
            --tmp C:\duckdb_tmp --estagio C:\duckdb_tmp\estagio --paralelo 3

    Chamar pelo caminho completo sempre funciona, porque nao passa pelo
    PATH. Se algum dia o uv sumir do lugar, este script acha de novo.
    ---------------------------------------------------------------------

    O que este script faz:

      1. Localiza o uv em disco (nao pelo PATH) e roda 'uv sync'.
      2. Se nao houver uv, monta o ambiente com venv + pip, escolhendo um
         Python que nao seja o do conda (o do Anaconda cria venv sem pip).
      3. Instala um ATALHO no seu perfil do PowerShell, para que 'uv'
         passe a funcionar como comando em toda sessao nova -- sem mexer
         no PATH, que em maquina corporativa costuma ser reescrito pela
         politica de grupo a cada logon.
      4. Grava COMO-RODAR.txt na pasta do projeto com os comandos prontos.

    NOTA: arquivo em ASCII puro de proposito. O PowerShell 5.1 le .ps1 sem
    BOM como cp1252, e acento vira lixo que quebra o parser.

.EXAMPLE
    .\pdet-setup.ps1
    .\pdet-setup.ps1 -Verificar
    .\pdet-setup.ps1 -Recriar
    .\pdet-setup.ps1 -SemAtalho
    .\pdet-setup.ps1 -SemUv -Recriar

.NOTES
    Se der "execucao de scripts desabilitada", rode uma vez:
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

[CmdletBinding()]
param(
    [switch]$Recriar,
    [switch]$Verificar,
    [switch]$Notebook,
    [switch]$SemUv,
    [switch]$SemAtalho,
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Raiz

function Info($m)  { Write-Host $m -ForegroundColor DarkGray }
function Aviso($m) { Write-Host "AVISO: $m" -ForegroundColor Yellow }
function Passo($m) { Write-Host "`n$m" -ForegroundColor Cyan }
function Falha($m) { Write-Host "`nERRO: $m" -ForegroundColor Red; exit 1 }

$PACOTES = @('duckdb>=1.1', 'pyarrow>=17', 'py7zr>=1.0', 'pandas>=2.2',
             'xlrd>=2.0', 'openpyxl>=3.1')
$venv   = Join-Path $Raiz '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$MARCA_INI = '# >>> pdet: atalho do uv >>>'
$MARCA_FIM = '# <<< pdet: atalho do uv <<<'

# ===========================================================================
# Localizar o uv em disco, ignorando o PATH
# ===========================================================================
function Find-UvExe {
    $cands = @()
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { $cands += $c.Source }
    $cands += @(
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\uv\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'uv\bin\uv.exe')
    )
    # pip install --user esconde o exe em %APPDATA%\Python\Python3XX\Scripts
    $appdataPy = Join-Path $env:APPDATA 'Python'
    if (Test-Path -LiteralPath $appdataPy) {
        $cands += (Get-ChildItem -Path $appdataPy -Filter 'uv.exe' -Recurse `
                   -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
    foreach ($p in $cands) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            try { $null = & $p --version 2>&1; return $p } catch { }
        }
    }
    return $null
}

# ===========================================================================
# Atalho no perfil do PowerShell
# ===========================================================================
function Install-Atalho {
    <#
      Por que perfil e nao PATH: em maquina corporativa a variavel PATH do
      usuario costuma ser reescrita pela politica de grupo a cada logon, e
      a alteracao evapora. O perfil e um .ps1 seu, que o PowerShell executa
      ao abrir toda sessao -- ninguem sobrescreve.

      Usamos CurrentUserAllHosts para valer tambem no terminal integrado do
      VS Code, nao so no console.
    #>
    param([string]$UvExe)

    $perfil = $PROFILE.CurrentUserAllHosts
    $pasta = Split-Path -Parent $perfil
    if (-not (Test-Path -LiteralPath $pasta)) {
        New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    }

    $bloco = @"
$MARCA_INI
# Deixa 'uv' utilizavel sem depender do PATH.
# Gerado por pdet-setup.ps1 -- pode apagar este bloco a vontade.
`$pdetUv = '$UvExe'
if (Test-Path -LiteralPath `$pdetUv) {
    Set-Alias -Name uv -Value `$pdetUv -Scope Global -Force
    `$pdetBin = Split-Path -Parent `$pdetUv
    if ((`$env:PATH -split ';') -notcontains `$pdetBin) {
        `$env:PATH = `$pdetBin + ';' + `$env:PATH
    }
}
$MARCA_FIM
"@

    $atual = ''
    if (Test-Path -LiteralPath $perfil) {
        $atual = Get-Content -LiteralPath $perfil -Raw -ErrorAction SilentlyContinue
        if ($null -eq $atual) { $atual = '' }
    }

    if ($atual -match [regex]::Escape($MARCA_INI)) {
        # substitui o bloco antigo, para nao acumular copias
        $padrao = [regex]::Escape($MARCA_INI) + '(?s).*?' + [regex]::Escape($MARCA_FIM)
        $novo = [regex]::Replace($atual, $padrao, $bloco.Replace('$', '$$'))
        Set-Content -LiteralPath $perfil -Value $novo -Encoding UTF8
        Info "  atalho atualizado em $perfil"
    } else {
        $sep = if ($atual.Trim()) { "`r`n`r`n" } else { '' }
        Set-Content -LiteralPath $perfil -Value ($atual + $sep + $bloco) -Encoding UTF8
        Info "  atalho instalado em $perfil"
    }

    # vale ja nesta sessao, sem precisar reabrir
    Set-Alias -Name uv -Value $UvExe -Scope Global -Force
    $bin = Split-Path -Parent $UvExe
    if (($env:PATH -split ';') -notcontains $bin) { $env:PATH = $bin + ';' + $env:PATH }
}

# ===========================================================================
# Ficha de comandos
# ===========================================================================
function Write-Ficha {
    param([string]$Chamada)
    $texto = @"
COMO RODAR O PROJETO PDET
=========================
(gerado por pdet-setup.ps1 -- se algo nao funcionar, rode o script de novo)

O comando que SEMPRE funciona, mesmo se o 'uv' nao for reconhecido:

    $Chamada sync
    $Chamada run python <script.py> <argumentos>

Depois de abrir um PowerShell NOVO, o atalho do perfil deixa isto valer:

    uv sync
    uv run python <script.py> <argumentos>

Se 'uv' voltar a nao ser reconhecido, use a forma de cima. Ela nao
depende do PATH nem do perfil.


PASSOS DO PROJETO
-----------------
1) Conferir os cabecalhos dos arquivos baixados:

    $Chamada run python pdet_cabecalhos.py --raw E:\pdet\00_raw

2) Ver o que seria convertido, sem converter nada:

    $Chamada run python pdet_parquet.py --raw E:\pdet\00_raw ``
        --saida E:\pdet\10_parquet --dry-run

3) Converter (comeca pelos anos recentes, para validar antes do resto):

    $Chamada run python pdet_parquet.py --raw E:\pdet\00_raw ``
        --saida E:\pdet\10_parquet --tmp C:\duckdb_tmp ``
        --estagio C:\duckdb_tmp\estagio --paralelo 3 ``
        --ano 2023 --ano 2024 --ano 2025

4) Backfill completo, parando no fim do expediente:

    $Chamada run python pdet_parquet.py --raw E:\pdet\00_raw ``
        --saida E:\pdet\10_parquet --tmp C:\duckdb_tmp ``
        --estagio C:\duckdb_tmp\estagio --paralelo 3 --ate-hora 17:20

   Rodar de novo no dia seguinte continua de onde parou: o manifesto em
   03_meta\conversao.csv registra cada unidade concluida.


LEMBRETES
---------
- --estagio precisa ficar no disco LOCAL (C:), nunca no HD externo.
- --tmp idem, e nunca dentro do OneDrive.
- Conferir o ambiente:  .\pdet-setup.ps1 -Verificar
- Refazer o ambiente:   .\pdet-setup.ps1 -Recriar
"@
    $destino = Join-Path $Raiz 'COMO-RODAR.txt'
    Set-Content -LiteralPath $destino -Value $texto -Encoding UTF8
    Info "  ficha de comandos gravada em COMO-RODAR.txt"
}

# ===========================================================================
# Procurar um Python 3.10+ utilizavel
# ===========================================================================
function Test-Py {
    param([string]$Exe, [string[]]$Pre = @())
    if (-not $Exe) { return $null }
    try {
        $v = & $Exe @Pre -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>&1
        if ($v -match '^(\d+)\.(\d+)$') {
            return @{ Exe = $Exe; Pre = $Pre; Maior = [int]$Matches[1];
                      Menor = [int]$Matches[2]; Versao = "$v" }
        }
    } catch { }
    return $null
}

function Find-Python {
    $achados = @()
    if ($Python) {
        $r = Test-Py $Python
        if (-not $r) { Falha "nao consegui usar o Python de -Python: $Python" }
        return @($r)
    }
    foreach ($c in @('python', 'python3')) {
        $g = Get-Command $c -ErrorAction SilentlyContinue
        if ($g) { $r = Test-Py $g.Source; if ($r) { $achados += $r } }
    }
    $pyl = Get-Command py -ErrorAction SilentlyContinue
    if ($pyl) {
        foreach ($tag in @('-3.13', '-3.12', '-3.11', '-3.10', '-3')) {
            $r = Test-Py $pyl.Source @($tag)
            if ($r) { $achados += $r }
        }
    }
    $raizes = @()
    foreach ($b in @($env:USERPROFILE, $env:LOCALAPPDATA, 'C:\ProgramData', 'C:\')) {
        if (-not $b) { continue }
        foreach ($n in @('anaconda3', 'miniconda3', 'miniforge3', 'Anaconda3',
                         'Miniconda3', 'mambaforge')) {
            $raizes += (Join-Path $b $n)
        }
    }
    $progs = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $progs) {
        $raizes += (Get-ChildItem $progs -Directory -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.FullName })
    }
    if ($env:CONDA_PREFIX) { $raizes += $env:CONDA_PREFIX }
    foreach ($r in $raizes) {
        $exe = Join-Path $r 'python.exe'
        if (Test-Path -LiteralPath $exe) {
            $t = Test-Py $exe
            if ($t) { $achados += $t }
        }
    }
    $vistos = @{}; $saida = @()
    foreach ($a in ($achados | Sort-Object -Property Maior, Menor -Descending)) {
        $k = "$($a.Exe) $($a.Pre -join ' ')"
        if (-not $vistos.ContainsKey($k)) { $vistos[$k] = $true; $saida += $a }
    }
    return $saida
}

# ===========================================================================
# Verificacao
# ===========================================================================
function Invoke-Verificacao {
    param([string]$Exe, [string[]]$Pre = @())
    $codigo = @'
import sys
print("Python       : %s" % sys.version.split()[0])
print("Executavel   : %s" % sys.executable)
falhou = False
for nome in ("duckdb", "pyarrow", "py7zr", "pandas", "xlrd", "openpyxl"):
    try:
        m = __import__(nome)
        print("  %-10s %s" % (nome, getattr(m, "__version__", "ok")))
    except ImportError as e:
        print("  %-10s FALTANDO (%s)" % (nome, e))
        falhou = True
try:
    import py7zr.io  # noqa: F401
    print("  py7zr.io   presente -> descompressao em streaming disponivel")
except ImportError:
    print("  py7zr.io   AUSENTE -> py7zr antigo. O conversor ainda funciona,")
    print("             mas extrai o .txt para disco antes de converter.")
    falhou = True
sys.exit(1 if falhou else 0)
'@
    $tmp = Join-Path $env:TEMP ("pdet_check_{0}.py" -f [guid]::NewGuid().ToString('N'))
    Set-Content -LiteralPath $tmp -Value $codigo -Encoding ASCII
    try {
        & $Exe @Pre $tmp
        return ($LASTEXITCODE -eq 0)
    } finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
}

# ===========================================================================
# Execucao
# ===========================================================================
if ($Recriar -and (Test-Path -LiteralPath $venv)) {
    Passo "Apagando o .venv anterior..."
    Remove-Item -Recurse -Force $venv
}

if ($Verificar) {
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Falha ".venv nao existe ainda. Rode sem -Verificar."
    }
    if (Invoke-Verificacao $venvPy) {
        Write-Host "`nAmbiente ok." -ForegroundColor Green
        $u = Find-UvExe
        if ($u) { Info ("uv: {0}" -f $u) }
        exit 0
    }
    Falha "ambiente incompleto. Rode com -Recriar."
}

$pronto = $false
$chamada = ''
$uv = $null

# --- caminho 1: uv pelo caminho completo -----------------------------------
if (-not $SemUv) {
    $uv = Find-UvExe
    if ($uv) {
        Info ("uv encontrado: {0}" -f $uv)
        Info ("versao       : {0}" -f (& $uv --version))
        if (Test-Path -LiteralPath (Join-Path $Raiz 'pyproject.toml')) {
            Passo "Instalando com uv..."
            $argl = @('sync')
            if ($Notebook) { $argl += @('--group', 'notebook') }
            & $uv @argl
            if ($LASTEXITCODE -eq 0) {
                $pronto = $true
                $chamada = "& `"$uv`""
            } else {
                Aviso "uv sync falhou (codigo $LASTEXITCODE). Tentando venv + pip."
            }
        } else {
            Aviso "pyproject.toml nao encontrado; indo para venv + pip."
        }
    } else {
        Info "uv nao encontrado em disco. Seguindo sem ele -- nao faz falta."
    }
}

# --- caminho 2: venv + pip -------------------------------------------------
if (-not $pronto) {
    Passo "Montando o ambiente com venv + pip (sem uv, sem administrador)..."
    $pys = Find-Python
    if (-not $pys) { Falha "nenhum Python encontrado na maquina." }

    Info "Pythons encontrados:"
    foreach ($p in $pys) {
        $marca = if ($p.Maior -gt 3 -or ($p.Maior -eq 3 -and $p.Menor -ge 10)) { "ok   " } else { "velho" }
        Info ("  [{0}] {1}  {2} {3}" -f $marca, $p.Versao, $p.Exe, ($p.Pre -join ' '))
    }

    $servem = $pys | Where-Object { $_.Maior -gt 3 -or ($_.Maior -eq 3 -and $_.Menor -ge 10) }
    # Prefere um Python que NAO seja do conda: o do Anaconda vem sem
    # ensurepip e cria venv sem pip.
    $bom = $servem | Where-Object {
        $_.Exe -notmatch '(?i)(anaconda|miniconda|miniforge|mambaforge)'
    } | Select-Object -First 1
    if (-not $bom) { $bom = $servem | Select-Object -First 1 }

    if (-not $bom) {
        Write-Host ""
        Write-Host "Todos os Pythons desta maquina sao anteriores ao 3.10, e o" -ForegroundColor Yellow
        Write-Host "py7zr 1.x (o que tem streaming) exige 3.10 ou mais novo." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Opcoes sem administrador:" -ForegroundColor Cyan
        Write-Host "  1. python.org -> instalador, marque 'Install just for me'"
        Write-Host "  2. Microsoft Store -> 'Python 3.12'"
        Write-Host "  3. winget install Python.Python.3.12 --scope user"
        Falha "sem Python 3.10+."
    }

    Info ("Usando: {0} {1} (Python {2})" -f $bom.Exe, ($bom.Pre -join ' '), $bom.Versao)

    if (-not (Test-Path -LiteralPath $venvPy)) {
        Passo "Criando o .venv..."
        & $bom.Exe @($bom.Pre) -m venv --copies $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
            $msg = "nao consegui criar o venv. Tente:`n  {0} -m venv --without-pip .venv"
            Falha ($msg -f $bom.Exe)
        }
    }

    # O Python do Anaconda costuma vir sem ensurepip, e ai o venv nasce sem
    # pip ("No module named pip"). Nao e falha de rede.
    & $venvPy -m pip --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Passo "O venv nasceu sem pip. Instalando o pip nele..."
        & $venvPy -m ensurepip --upgrade 2>&1 | Out-Null
        & $venvPy -m pip --version 2>&1 | Out-Null
    }
    if ($LASTEXITCODE -ne 0) {
        Info "  tentando pelo get-pip.py..."
        $getpip = Join-Path $env:TEMP 'get-pip.py'
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' `
                              -OutFile $getpip -UseBasicParsing
            & $venvPy $getpip --no-warn-script-location
            Remove-Item -LiteralPath $getpip -ErrorAction SilentlyContinue
            & $venvPy -m pip --version 2>&1 | Out-Null
        } catch {
            Aviso ("nao consegui baixar o get-pip.py: {0}" -f $_.Exception.Message)
        }
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "O venv ficou sem pip. Isso e tipico do Python do Anaconda." -ForegroundColor Yellow
        Write-Host "Saida mais simples: use o uv -> .\pdet-setup.ps1" -ForegroundColor Cyan
        Write-Host "Ou escolha outro Python:" -ForegroundColor Cyan
        Write-Host "  .\pdet-setup.ps1 -SemUv -Recriar -Python C:\WINDOWS\py.exe" -ForegroundColor Cyan
        Falha "sem pip no venv."
    }

    Passo "Instalando os pacotes..."
    & $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
    $lista = if ($Notebook) { $PACOTES + @('jupyterlab>=4.2', 'matplotlib>=3.9') } else { $PACOTES }
    & $venvPy -m pip install --disable-pip-version-check @lista
    if ($LASTEXITCODE -ne 0) {
        Aviso "o pip falhou. Em rede corporativa costuma ser o proxy/TLS."
        $modelo = "    {0} -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org {1}"
        Info ($modelo -f $venvPy, ($lista -join ' '))
        Falha "instalacao das dependencias falhou."
    }
    $pronto = $true
    $chamada = ".\.venv\Scripts\python.exe"
}

# --- verificacao -----------------------------------------------------------
Passo "Verificando..."
if (-not (Test-Path -LiteralPath $venvPy)) {
    Falha "o .venv nao apareceu onde eu esperava ($venv)."
}
if (-not (Invoke-Verificacao $venvPy)) {
    Aviso "o ambiente ficou incompleto. Rode com -Recriar."
    exit 1
}

# --- atalho e ficha --------------------------------------------------------
Passo "Deixando o ambiente facil de usar..."
if ($uv -and -not $SemAtalho) {
    Install-Atalho -UvExe $uv
} elseif ($SemAtalho) {
    Info "  atalho nao instalado (-SemAtalho)"
}
Write-Ficha -Chamada $chamada

Write-Host "`nAmbiente pronto." -ForegroundColor Green

if ($uv -and -not $SemAtalho) {
    Write-Host @"

DE AGORA EM DIANTE
------------------
Nesta sessao e em toda sessao NOVA do PowerShell, isto ja funciona:

    uv sync
    uv run python pdet_parquet.py --raw E:\pdet\00_raw --saida E:\pdet\10_parquet

O atalho foi gravado no seu perfil ($($PROFILE.CurrentUserAllHosts)),
que o PowerShell le ao abrir. Nao dependemos mais do PATH -- em maquina
corporativa a politica de grupo costuma reescrever o PATH do usuario a
cada logon, e por isso a alteracao nao ficava.

SE 'uv' AINDA ASSIM NAO FOR RECONHECIDO
---------------------------------------
Alguma politica pode estar bloqueando a execucao do perfil. Confira com:

    Get-ExecutionPolicy -List
    Test-Path $($PROFILE.CurrentUserAllHosts)

Nesse caso, use sempre a forma abaixo, que nunca falha:

    $chamada sync
    $chamada run python pdet_parquet.py ...

Os comandos prontos estao em COMO-RODAR.txt, na pasta do projeto.
"@ -ForegroundColor Gray
} else {
    Write-Host @"

COMO RODAR
----------
    $chamada pdet_parquet.py --raw E:\pdet\00_raw --saida E:\pdet\10_parquet

Os comandos prontos estao em COMO-RODAR.txt, na pasta do projeto.
"@ -ForegroundColor Gray
}