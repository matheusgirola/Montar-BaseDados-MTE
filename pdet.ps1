<#
.SYNOPSIS
    Lancador Windows para o pipeline de microdados do PDET/MTE.

.DESCRIPTION
    Resolve o que e especifico do Windows antes de chamar o Python:
    encoding do console, caminhos longos (>260 chars), suspensao da
    maquina durante downloads longos, localizacao do 7-Zip e checagem
    do sistema de arquivos do HD externo.

    NOTA: este arquivo e deliberadamente ASCII puro (sem acentos).
    O Windows PowerShell 5.1 le arquivos .ps1 como ANSI/cp1252 quando
    nao ha BOM, e caracteres UTF-8 viram aspas curvas que quebram o
    parser. ASCII puro funciona em qualquer encoding. Se for editar,
    mantenha assim ou salve como "UTF-8 with BOM".

.EXAMPLE
    .\pdet.ps1 inventario
    .\pdet.ps1 relatorio
    .\pdet.ps1 baixar -Base RAIS_VINCULOS -Recorte NORDESTE -Ano 2023,2024
    .\pdet.ps1 baixar -Base NOVO_CAGED -Extrair
    .\pdet.ps1 baixar -Base RAIS_VINCULOS -Ano 2015 -Efemero

    # usando um ambiente conda sem precisar ativa-lo antes:
    .\pdet.ps1 inventario -CondaEnv dados
    .\pdet.ps1 baixar -CondaEnv dados -Base RAIS_VINCULOS -Recorte NORDESTE

    # se o ambiente ja estiver ativo, nao precisa de nada: e detectado sozinho
    conda activate dados
    .\pdet.ps1 inventario

.NOTES
    Se der "execucao de scripts desabilitada", rode uma vez:
        Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('inventario', 'relatorio', 'baixar')]
    [string]$Comando = 'inventario',

    # >>> AJUSTE AQUI: raiz do projeto no HD externo <<<
    [string]$Dados = 'E:\pdet',

    [string[]]$Base = @(),
    [string[]]$Ano = @(),
    [string[]]$Recorte = @(),

    # --- escolha do interpretador Python ---
    # -CondaEnv : nome do ambiente (ex.: 'dados') ou caminho completo dele
    # -Conda    : usa o ambiente conda ATIVO, ou o 'base' se nenhum estiver ativo
    # -Python   : caminho explicito de um python.exe (venv, instalacao especifica)
    [string]$CondaEnv = '',
    [switch]$Conda,
    [string]$Python = '',

    [switch]$Extrair,
    [switch]$Efemero,      # extrai e descarta o .7z (nao guarda base local)
    [switch]$DryRun,
    [switch]$Resume,
    [switch]$SemHash
)

$ErrorActionPreference = 'Stop'
$script:Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# 1. Encoding do console
#    Sem isto, nomes de pasta acentuados ("NOVO CAGED") saem como lixo.
# ---------------------------------------------------------------------------
try {
    $null = & chcp.com 65001 2>&1
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch {
    Write-Host "AVISO: nao consegui mudar o console para UTF-8." -ForegroundColor Yellow
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
function Test-PythonExe {
    param([string]$Caminho, [string[]]$Prefixo = @())
    if (-not $Caminho) { return $null }
    if (-not (Test-Path -LiteralPath $Caminho)) { return $null }
    try {
        $v = & $Caminho @Prefixo --version 2>&1
        if ($v -match 'Python 3\.(\d+)' -and [int]$Matches[1] -ge 8) {
            return @{ Exe = $Caminho; Prefix = $Prefixo; Versao = "$v" }
        }
    } catch { }
    return $null
}

function Find-CondaRoot {
    # 1) conda ja inicializado no shell
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE)) {
        return (Split-Path -Parent (Split-Path -Parent $env:CONDA_EXE))
    }
    # 2) conda no PATH
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($cmd) {
        $d = Split-Path -Parent $cmd.Source
        foreach ($cand in @($d, (Split-Path -Parent $d))) {
            if (Test-Path -LiteralPath (Join-Path $cand 'python.exe')) { return $cand }
        }
    }
    # 3) locais padrao de instalacao
    $bases = @()
    foreach ($raiz in @($env:USERPROFILE, $env:LOCALAPPDATA, 'C:\ProgramData', 'C:\')) {
        if (-not $raiz) { continue }
        foreach ($nome in @('anaconda3', 'miniconda3', 'miniforge3', 'mambaforge', 'Anaconda3', 'Miniconda3')) {
            $bases += (Join-Path $raiz $nome)
        }
    }
    foreach ($b in $bases) {
        if (Test-Path -LiteralPath (Join-Path $b 'python.exe')) { return $b }
    }
    return $null
}

function Enable-CondaEnv {
    <#
      Coloca no PATH os diretorios que o "conda activate" colocaria.
      Isto NAO e opcional no Windows: chamar envs\nome\python.exe direto,
      sem esses diretorios, faz pacotes compilados (pyarrow, duckdb, numpy)
      falharem com "DLL load failed while importing ...". As DLLs moram em
      Library\bin, fora do alcance do interpretador.
    #>
    param([string]$EnvRoot)
    $dirs = @(
        $EnvRoot,
        (Join-Path $EnvRoot 'Library\mingw-w64\bin'),
        (Join-Path $EnvRoot 'Library\usr\bin'),
        (Join-Path $EnvRoot 'Library\bin'),
        (Join-Path $EnvRoot 'Scripts'),
        (Join-Path $EnvRoot 'bin')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    $env:PATH = ($dirs -join ';') + ';' + $env:PATH
    $env:CONDA_PREFIX = $EnvRoot
    $env:CONDA_DEFAULT_ENV = Split-Path -Leaf $EnvRoot
}

function Resolve-CondaEnv {
    param([string]$Nome)
    # caminho completo do ambiente
    if ($Nome -and (Test-Path -LiteralPath (Join-Path $Nome 'python.exe'))) {
        return (Resolve-Path -LiteralPath $Nome).Path
    }
    $root = Find-CondaRoot
    if (-not $root) { return $null }
    if (-not $Nome -or $Nome -eq 'base') { return $root }

    # <root>\envs\<nome>
    $cand = Join-Path $root ('envs\' + $Nome)
    if (Test-Path -LiteralPath (Join-Path $cand 'python.exe')) { return $cand }

    # ambientes criados com --prefix ou em outros diretorios: pergunta ao conda
    $condaExe = Join-Path $root 'Scripts\conda.exe'
    if (Test-Path -LiteralPath $condaExe) {
        try {
            $linhas = & $condaExe env list 2>$null
            foreach ($l in $linhas) {
                if ($l -match '^\s*#') { continue }
                $p = ($l -replace '^\S+\s+', '') -replace '\*\s+', ''
                $p = $p.Trim()
                if ($p -and (Split-Path -Leaf $p) -eq $Nome -and
                    (Test-Path -LiteralPath (Join-Path $p 'python.exe'))) {
                    return $p
                }
            }
        } catch { }
    }
    return $null
}

function Find-Python {
    # --- 1. -Python: caminho explicito, prioridade maxima ---
    if ($Python) {
        $r = Test-PythonExe -Caminho $Python
        if ($r) { $r.Origem = 'explicito'; return $r }
        throw ("Nao consegui usar o Python indicado em -Python: {0}" -f $Python)
    }

    # --- 2. -CondaEnv: ambiente conda nomeado ---
    if ($CondaEnv) {
        $envRoot = Resolve-CondaEnv -Nome $CondaEnv
        if (-not $envRoot) {
            throw ("Ambiente conda '{0}' nao encontrado. Liste os disponiveis com: conda env list" -f $CondaEnv)
        }
        Enable-CondaEnv -EnvRoot $envRoot
        $r = Test-PythonExe -Caminho (Join-Path $envRoot 'python.exe')
        if ($r) { $r.Origem = ("conda: " + (Split-Path -Leaf $envRoot)); return $r }
        throw ("Ambiente '{0}' existe mas o python de dentro nao respondeu." -f $CondaEnv)
    }

    # --- 3. ambiente conda JA ATIVO no shell ---
    if ($env:CONDA_PREFIX) {
        $r = Test-PythonExe -Caminho (Join-Path $env:CONDA_PREFIX 'python.exe')
        if ($r) { $r.Origem = ("conda ativo: " + $env:CONDA_DEFAULT_ENV); return $r }
    }

    # --- 4. -Conda sem nome: usa o base ---
    if ($Conda) {
        $envRoot = Resolve-CondaEnv -Nome 'base'
        if (-not $envRoot) {
            throw "Nao encontrei nenhuma instalacao do conda. Use -CondaEnv com o caminho completo do ambiente."
        }
        Enable-CondaEnv -EnvRoot $envRoot
        $r = Test-PythonExe -Caminho (Join-Path $envRoot 'python.exe')
        if ($r) { $r.Origem = 'conda: base'; return $r }
    }

    # --- 5. virtualenv ativo (.venv) ---
    if ($env:VIRTUAL_ENV) {
        $r = Test-PythonExe -Caminho (Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe')
        if ($r) { $r.Origem = 'venv ativo'; return $r }
    }

    # --- 6. Python do sistema ---
    foreach ($c in @('py', 'python', 'python3')) {
        $exe = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $prefixo = if ($c -eq 'py') { @('-3') } else { @() }
        $r = Test-PythonExe -Caminho $exe.Source -Prefixo $prefixo
        if ($r) { $r.Origem = 'sistema'; return $r }
    }

    throw @"
Python 3.8+ nao encontrado.

Opcoes:
  - Instale de https://python.org marcando 'Add Python to PATH'
  - Se usa conda:      .\pdet.ps1 $Comando -CondaEnv nome_do_ambiente
  - Ou ative antes:    conda activate nome_do_ambiente
  - Ou aponte direto:  .\pdet.ps1 $Comando -Python "C:\caminho\python.exe"
"@
}

$py = Find-Python
Write-Host ("Python       : {0}" -f $py.Exe) -ForegroundColor DarkGray
Write-Host ("               {0} [{1}]" -f $py.Versao, $py.Origem) -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# 3. Caminhos longos (limite de 260 caracteres)
# ---------------------------------------------------------------------------
$lp = 0
try {
    $lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
            -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled
} catch {
    $lp = 0
}
if ($lp -ne 1) {
    Write-Host "AVISO: caminhos longos desabilitados. O Python contorna com o" -ForegroundColor Yellow
    Write-Host "       prefixo \\?\, mas Explorer e Excel podem falhar. Para ligar," -ForegroundColor Yellow
    Write-Host "       abra o PowerShell como Administrador e rode:" -ForegroundColor Yellow
    Write-Host "       Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. HD externo: montado? formato? espaco?
# ---------------------------------------------------------------------------
if ($Comando -eq 'baixar') {
    if ($Dados -match '^([A-Za-z]):') {
        $letra = $Matches[1]
        if (-not (Test-Path -LiteralPath ($letra + ':\'))) {
            throw ("Drive {0}: nao esta montado. Conecte o HD externo." -f $letra)
        }
        try {
            $vol = Get-Volume -DriveLetter $letra -ErrorAction Stop
            $fs = $vol.FileSystemType
            $livreGB = [math]::Round($vol.SizeRemaining / 1GB, 1)
            Write-Host ("Drive {0}:      {1} - {2} GB livres" -f $letra, $fs, $livreGB) -ForegroundColor DarkGray

            if ($fs -eq 'FAT32') {
                throw "FAT32 nao aceita arquivos acima de 4 GB, e os .txt da RAIS passam disso. Reformate o drive como NTFS ou exFAT."
            }
            if ($fs -eq 'exFAT') {
                Write-Host "AVISO: exFAT nao tem journaling. Uma queda de energia durante" -ForegroundColor Yellow
                Write-Host "       a gravacao pode corromper a pasta. NTFS e mais seguro" -ForegroundColor Yellow
                Write-Host "       se o drive so for usado no Windows." -ForegroundColor Yellow
            }
        } catch [System.Management.Automation.CommandNotFoundException] {
            Write-Host "AVISO: Get-Volume indisponivel; pulando checagem do sistema de arquivos." -ForegroundColor Yellow
        }
    }

    New-Item -ItemType Directory -Force -Path $Dados | Out-Null

    # Windows Defender escaneia cada .txt extraido e isso pode triplicar o tempo
    try {
        $excl = (Get-MpPreference -ErrorAction Stop).ExclusionPath
        if ($excl -notcontains $Dados) {
            Write-Host "DICA: exclua a pasta do Defender (como Admin) para acelerar:" -ForegroundColor Cyan
            Write-Host ("      Add-MpPreference -ExclusionPath '{0}'" -f $Dados) -ForegroundColor Cyan
        }
    } catch {
        # Defender ausente ou sem permissao: segue sem avisar
    }
}

# ---------------------------------------------------------------------------
# 5. 7-Zip
# ---------------------------------------------------------------------------
if ($Extrair -or $Efemero) {
    $z = $null
    $candidatos = @(
        (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
        (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
    )
    foreach ($c in $candidatos) {
        if ($c -and (Test-Path -LiteralPath $c)) { $z = $c; break }
    }
    if (-not $z) {
        $cmd = Get-Command 7z -ErrorAction SilentlyContinue
        if ($cmd) { $z = $cmd.Source }
    }
    if ($z) {
        Write-Host ("7-Zip        : {0}" -f $z) -ForegroundColor DarkGray
    } else {
        Write-Host "AVISO: 7-Zip nao encontrado. O Python usara py7zr, que e bem" -ForegroundColor Yellow
        Write-Host "       mais lento. Instale com: winget install 7zip.7zip" -ForegroundColor Yellow
        & $py.Exe @($py.Prefix) -m pip install --user --quiet py7zr
    }
}

# ---------------------------------------------------------------------------
# 6. Impedir suspensao durante o download
# ---------------------------------------------------------------------------
$energiaOk = $false
if (-not ('PdetEnergia' -as [type])) {
    $assinatura = '[DllImport("kernel32.dll", SetLastError = true)] public static extern uint SetThreadExecutionState(uint esFlags);'
    try {
        Add-Type -Name PdetEnergia -Namespace Pdet -MemberDefinition $assinatura
        $energiaOk = $true
    } catch {
        Write-Host "AVISO: nao consegui bloquear a suspensao automatica. Se o PC dormir," -ForegroundColor Yellow
        Write-Host "       o download para, mas retoma quando voce rodar de novo." -ForegroundColor Yellow
    }
} else {
    $energiaOk = $true
}
$ES_CONTINUOUS = [uint32]'0x80000000'
$ES_SYSTEM_REQUIRED = [uint32]'0x00000001'
if ($energiaOk) {
    $null = [Pdet.PdetEnergia]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
}

# ---------------------------------------------------------------------------
# 7. Monta os argumentos e executa
# ---------------------------------------------------------------------------
try {
    $a = @()
    switch ($Comando) {
        'inventario' {
            $a = @('pdet_inventario.py', 'crawl')
            if ($Resume) { $a += '--resume' } else { $a += '--force' }
        }
        'relatorio' {
            $a = @('pdet_inventario.py', 'report')
        }
        'baixar' {
            $a = @('pdet_download.py', '--dados', $Dados)
            foreach ($b in $Base)    { $a += @('--base', $b) }
            foreach ($y in $Ano)     { $a += @('--ano', "$y") }
            foreach ($r in $Recorte) { $a += @('--recorte', $r) }
            if ($Extrair -or $Efemero) { $a += '--extrair' }
            if ($Efemero) { $a += '--apagar-apos-extrair' }
            if ($DryRun)  { $a += '--dry-run' }
            if ($SemHash) { $a += '--sem-hash' }
        }
    }

    Write-Host ''
    Push-Location $script:Raiz
    try {
        & $py.Exe @($py.Prefix) @a
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($code -ne 0) {
        Write-Host ("`nTerminou com erros (codigo {0})." -f $code) -ForegroundColor Red
    }
    exit $code
}
finally {
    # devolve o controle de energia ao Windows
    if ($energiaOk) {
        $null = [Pdet.PdetEnergia]::SetThreadExecutionState($ES_CONTINUOUS)
    }
}