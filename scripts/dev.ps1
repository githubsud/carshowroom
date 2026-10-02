<#
.SYNOPSIS
  SayyaraDMS developer commands for Windows (mirrors the Makefile).
.EXAMPLE
  ./scripts/dev.ps1 setup
  ./scripts/dev.ps1 db-start   # also writes apps/api/.env
  ./scripts/dev.ps1 dev      # API and web in new windows
  ./scripts/dev.ps1 test
#>
param([Parameter(Mandatory = $true)][string]$Command)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root 'apps/api'
$Web = Join-Path $Root 'apps/web'
$Py = Join-Path $Api '.venv/Scripts/python.exe'

function Invoke-Checked([scriptblock]$Block) {
  & $Block
  if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}

switch ($Command) {
  'setup' {
    Invoke-Checked { py -3.12 -m venv (Join-Path $Api '.venv') }
    Invoke-Checked { & $Py -m pip install -e "$Api[dev]" }
    if (-not (Test-Path (Join-Path $Api '.env'))) { Copy-Item (Join-Path $Api '.env.example') (Join-Path $Api '.env') }
    Push-Location $Web; try { Invoke-Checked { npm ci }; Invoke-Checked { npx playwright install chromium } } finally { Pop-Location }
  }
  'db-start' {
    Push-Location $Root
    try { Invoke-Checked { npx supabase start -x studio,imgproxy,vector,logflare,edge-runtime,realtime,supavisor,postgres-meta } } finally { Pop-Location }
    & $PSCommandPath env
  }
  'env' {
    # apps/api/.env from the template, plus the local secret key read from the running stack
    # (secrets are never stored in git).
    $envFile = Join-Path $Api '.env'
    if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $Api '.env.example') $envFile }
    Push-Location $Root
    # supabase status lists excluded services on stderr; that is informational, not an error.
    try { $status = $($ErrorActionPreference = 'Continue'; npx supabase status -o env 2>$null) } finally { Pop-Location }
    $secret = ($status | Where-Object { $_ -like 'SECRET_KEY=*' }) -replace '^SECRET_KEY=', '' -replace '"', ''
    if (-not $secret) { throw 'Local Supabase is not running; run db-start first.' }
    $lines = Get-Content $envFile | ForEach-Object { if ($_ -like 'SUPABASE_SERVICE_ROLE_KEY=*') { "SUPABASE_SERVICE_ROLE_KEY=$secret" } else { $_ } }
    # A local AES key for national IDs, generated once (never committed; DECISIONS D-05).
    if (-not ($lines | Where-Object { $_ -match '^NATIONAL_ID_KEY=.+' })) {
      $bytes = New-Object byte[] 32
      [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
      $key = [Convert]::ToBase64String($bytes)
      if ($lines | Where-Object { $_ -like 'NATIONAL_ID_KEY=*' }) {
        $lines = $lines | ForEach-Object { if ($_ -like 'NATIONAL_ID_KEY=*') { "NATIONAL_ID_KEY=$key" } else { $_ } }
      } else { $lines += "NATIONAL_ID_KEY=$key" }
    }
    Set-Content -Path $envFile -Value $lines -Encoding utf8
    Write-Host 'apps/api/.env is ready.'
  }
  'db-reset' { Push-Location $Root; try { Invoke-Checked { npx supabase db reset } } finally { Pop-Location } }
  'db-test'  { Push-Location $Root; try { Invoke-Checked { npx supabase test db } } finally { Pop-Location } }
  'api' { Push-Location $Api; try { & $Py -m uvicorn app.main:create_app --factory --reload --port 8000 } finally { Pop-Location } }
  'web' {
    # PrimeUI licence key from the environment (never committed; DECISIONS D-61).
    $define = @()
    if ($env:PRIMEUI_LICENSE) { $define = @('--', '--define', "PRIMEUI_LICENSE=`"'$($env:PRIMEUI_LICENSE)'`"") }
    Push-Location $Web; try { npm start @define } finally { Pop-Location }
  }
  'dev' {
    & $PSCommandPath db-start
    Start-Process powershell -ArgumentList '-NoExit', '-File', $PSCommandPath, 'api'
    Start-Process powershell -ArgumentList '-NoExit', '-File', $PSCommandPath, 'web'
    # Opening the app before the API is up shows "cannot reach the server": wait for both.
    foreach ($target in @(@{ Name = 'API'; Url = 'http://localhost:8000/readyz' }, @{ Name = 'Web'; Url = 'http://localhost:4200' })) {
      Write-Host -NoNewline "Waiting for $($target.Name)"
      $deadline = (Get-Date).AddMinutes(5)
      while ($true) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $target.Url | Out-Null; break } catch { }
        if ((Get-Date) -gt $deadline) { throw "$($target.Name) did not start; check its window for errors." }
        Write-Host -NoNewline '.'; Start-Sleep -Seconds 2
      }
      Write-Host ' ready'
    }
    Write-Host 'Open http://localhost:4200  (demo: owner@nour.example / Demo-Pass-2026)'
  }
  'test' {
    & $PSCommandPath db-test
    Push-Location $Api; try { Invoke-Checked { & $Py -m pytest } } finally { Pop-Location }
    Push-Location $Web; try { Invoke-Checked { npm test }; Invoke-Checked { npx playwright test } } finally { Pop-Location }
  }
  'lint' {
    Push-Location $Api
    try { Invoke-Checked { & $Py -m ruff check . }; Invoke-Checked { & $Py -m ruff format --check . }; Invoke-Checked { & $Py -m mypy } } finally { Pop-Location }
    Push-Location $Web; try { Invoke-Checked { npm run lint }; Invoke-Checked { npm run lint:styles } } finally { Pop-Location }
  }
  default { throw "Unknown command '$Command'. Use: setup, db-start, env, db-reset, db-test, api, web, dev, test, lint" }
}
