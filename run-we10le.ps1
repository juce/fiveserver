param(
    [string]$Venv = ".local"
)

$ErrorActionPreference = "Stop"
$serverRoot = $PSScriptRoot
$venvRoot = if ([System.IO.Path]::IsPathRooted($Venv)) {
    $Venv
} else {
    Join-Path $serverRoot $Venv
}
$twistdPath = Join-Path $venvRoot "Scripts\twistd.exe"
if (-not (Test-Path -LiteralPath $twistdPath)) {
    throw "Install pip.requirements-we10le into a virtual environment first. See docs/WE10LE-KR.md."
}
$env:FSROOT = $serverRoot
$env:PYTHONPATH = (Join-Path $serverRoot "lib") + [IO.Path]::PathSeparator + $env:PYTHONPATH
Push-Location -LiteralPath $serverRoot
try {
    & $twistdPath -noy (Join-Path $serverRoot "tac\we10le.tac")
    if ($LASTEXITCODE -ne 0) {
        throw "WE10LE server exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
