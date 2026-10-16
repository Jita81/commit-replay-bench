# exmap/start.ps1 — one command on Windows (PowerShell 5.1+ or 7)
$ErrorActionPreference = "Stop"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  Write-Error "exmap needs Node.js 22.12 or newer, and 'node' was not found. Install it from https://nodejs.org (LTS), reopen the terminal, and run this again."
  exit 2
}
& $node.Source (Join-Path $PSScriptRoot "bin\exmap.mjs") @args
exit $LASTEXITCODE
