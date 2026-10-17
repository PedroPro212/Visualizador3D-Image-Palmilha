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

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python -c 'import pip, pip._vendor.urllib3' 2>$null
    $pipCheckExitCode = $LASTEXITCODE
    if ($pipCheckExitCode -ne 0) {
        Write-Host 'Reparando o instalador Python...'
        $sitePackages = & $python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
        if ($LASTEXITCODE -ne 0 -or -not $sitePackages) { throw 'Nao foi possivel localizar os arquivos do pip.' }
        Remove-Item -LiteralPath (Join-Path $sitePackages 'pip') -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'pip-*.dist-info' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        & $python -m ensurepip --upgrade 2>$null
        $repairExitCode = $LASTEXITCODE
        & $python -c 'import pip, pip._vendor.urllib3' 2>$null
        $pipCheckExitCode = $LASTEXITCODE
    }
    $ErrorActionPreference = $previousErrorActionPreference
    if ($pipCheckExitCode -ne 0) { throw 'Nao foi possivel reparar o pip. Verifique a instalacao do Python 3.11 a 3.14 e tente novamente.' }

    $stamp = Join-Path $PSScriptRoot '.venv-studio\requirements.sha256'
    $hash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
    if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
        Write-Host 'Preparando o Palmilha Studio. A primeira execucao precisa de internet...'
        $ErrorActionPreference = 'Continue'
        & $python -m pip install -r requirements.txt
        $installExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($installExitCode -ne 0) { throw 'Falha ao instalar bibliotecas. Verifique sua conexao.' }
        Set-Content $stamp $hash
    }

    $opencvPreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python -c 'import cv2' 2>$null
    $opencvCheckExitCode = $LASTEXITCODE
    if ($opencvCheckExitCode -ne 0) {
        Write-Host 'OpenCV incompleto. Reinstalando...'
        & $python -m pip install --force-reinstall --no-deps 'opencv-python-headless>=4.10,<6'
        $opencvInstallExitCode = $LASTEXITCODE
        if ($opencvInstallExitCode -eq 0) {
            & $python -c 'import cv2' 2>$null
            $opencvCheckExitCode = $LASTEXITCODE
        }
    }
    $ErrorActionPreference = $opencvPreviousPreference
    if ($opencvCheckExitCode -ne 0) { throw 'Nao foi possivel reparar o OpenCV. Verifique a conexao e tente novamente.' }

    & $python app.py
    if ($LASTEXITCODE -ne 0) { throw 'O aplicativo encerrou com erro. Confira a mensagem acima.' }
} catch {
    Write-Host $_ -ForegroundColor Red
    exit 1
}



