param([switch]$CompileInstaller)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$installerRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$payloadDir = [IO.Path]::GetFullPath((Join-Path $installerRoot 'payload'))
$workDir = [IO.Path]::GetFullPath((Join-Path $installerRoot 'pyinstaller-build'))
$tempDir = [IO.Path]::GetFullPath((Join-Path $installerRoot 'temp'))
$outputDir = [IO.Path]::GetFullPath((Join-Path $installerRoot 'output'))
$redistDir = [IO.Path]::GetFullPath((Join-Path $installerRoot 'redist'))
$redistPath = Join-Path $redistDir 'vc_redist.x64.exe'
$redistUrl = 'https://aka.ms/vc14/vc_redist.x64.exe'
$python = Join-Path $projectRoot '.venv-studio\Scripts\python.exe'
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'

if (-not (Test-Path -LiteralPath $python)) { throw 'The .venv-studio environment was not found. Run INICIAR.bat first.' }
if (-not (Test-Path -LiteralPath $iscc)) { throw 'Inno Setup 6 was not found. Install Inno Setup 6 to build the installer.' }
New-Item -ItemType Directory -Force -Path $tempDir,$outputDir | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir
New-Item -ItemType Directory -Force -Path $redistDir | Out-Null
if (-not (Test-Path -LiteralPath $redistPath)) {
    Write-Host 'Downloading the official Microsoft Visual C++ runtime...'
    Invoke-WebRequest -Uri $redistUrl -OutFile $redistPath -MaximumRedirection 10
}
$signature = Get-AuthenticodeSignature -LiteralPath $redistPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Microsoft Corporation*') {
    throw 'The Visual C++ runtime signature is invalid.'
}

& $python -c 'import numpy, PIL, scipy, cv2, triangle, PySide6, pyqtgraph, OpenGL'
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies are incomplete.' }
& $python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing PyInstaller in the build environment...'
    & $python -m pip install PyInstaller
    if ($LASTEXITCODE -ne 0) { throw 'Could not install PyInstaller. Check the internet connection.' }
}

foreach ($target in @($payloadDir,$workDir)) {
    $fullTarget = [IO.Path]::GetFullPath($target)
    if (-not $fullTarget.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path is outside the project folder: $fullTarget"
    }
    if (Test-Path -LiteralPath $fullTarget) { Remove-Item -LiteralPath $fullTarget -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null

$pyinstallerArgs = @(
    '-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
    '--name','PalmilhaStudio',
    '--distpath',$payloadDir,
    '--workpath',$workDir,
    '--specpath',$installerRoot,
    '--hidden-import','PySide6.QtOpenGLWidgets',
    '--hidden-import','PySide6.QtOpenGL',
    (Join-Path $projectRoot 'app.py')
)
& $python @pyinstallerArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to package the application.' }

$appExe = Join-Path $payloadDir 'PalmilhaStudio\PalmilhaStudio.exe'
if (-not (Test-Path -LiteralPath $appExe)) { throw 'The packaged executable was not created.' }

# Fail early if the frozen app cannot load Qt without Python or development tools on PATH.
$smokeOut = Join-Path $tempDir 'smoke-out.txt'
$smokeErr = Join-Path $tempDir 'smoke-err.txt'
$null = Set-Content -LiteralPath $smokeOut -Value ''
$null = Set-Content -LiteralPath $smokeErr -Value ''
$process = $null
try {
    $process = Start-Process -FilePath $appExe -PassThru -RedirectStandardOutput $smokeOut -RedirectStandardError $smokeErr
    Start-Sleep -Seconds 8
    if ($process.HasExited) {
        $details = (Get-Content $smokeErr,$smokeOut -ErrorAction SilentlyContinue | Out-String)
        throw "The packaged app exited during the startup check. $details"
    }
    Stop-Process -Id $process.Id -Force
    $startupText = (Get-Content $smokeErr,$smokeOut -ErrorAction SilentlyContinue | Out-String)
    if ($startupText -match 'Traceback|Unhandled exception|OpenGL\.error\.GLError') {
        throw "The packaged app reported a startup/rendering exception. $startupText"
    }
} finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

Write-Host "App payload created and startup checked: $appExe"
if ($CompileInstaller) {
    & $iscc (Join-Path $installerRoot 'PalmilhaStudio-com-logo.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed to compile the installer.' }
    Write-Host "Installer created at: $outputDir"
} else {
    Write-Host 'Open installer\PalmilhaStudio-com-logo.iss in Inno Setup and press Compile to create the installer.'
}
