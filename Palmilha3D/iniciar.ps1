$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv-studio\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $candidates = @()
        foreach ($version in @('3.12','3.13','3.14','3.11')) {
            try {
                $found = & py "-$version" -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $found) { $candidates += $found }
            } catch { }
        }
        $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
        $candidates += @(Get-ChildItem "$env:USERPROFILE\.cache\codex-runtimes\*\dependencies\python\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
        $runtime = $null
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate) {
                & $candidate -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,15) else 1)'
                if ($LASTEXITCODE -eq 0) { $runtime = $candidate; break }
            }
        }
        if (-not $runtime) { throw 'Instale Python 3.12 (64 bits) em https://www.python.org/downloads/ e abra novamente.' }
        & $runtime -m venv .venv-studio
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente Python.' }
    }
    $stamp = Join-Path $PSScriptRoot '.venv-studio\requirements.sha256'
    $hash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
    if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
        Write-Host 'Preparando o Palmilha Studio. A primeira execucao precisa de internet...'
        & $python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar bibliotecas. Verifique sua conexao.' }
        Set-Content $stamp $hash
    }
    & $python app.py
    if ($LASTEXITCODE -ne 0) { throw 'O aplicativo encerrou com erro. Confira a mensagem acima.' }
} catch {
    Write-Host $_ -ForegroundColor Red
    exit 1
}
