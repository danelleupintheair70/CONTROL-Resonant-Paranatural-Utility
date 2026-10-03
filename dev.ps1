# Doblarr local dev helper (Windows / PowerShell)
#
#   .\dev.ps1 setup          install Python + Node deps
#   .\dev.ps1 serve          build the web UI, run it + the API (http://127.0.0.1:6363)
#   .\dev.ps1 ui             web UI dev server with live reload (http://127.0.0.1:5363)
#   .\dev.ps1 validate       watch Python + UI files; lint, type-check and test on every save
#   .\dev.ps1 validate once  the same checks once (exit code 1 on any failure)
#   .\dev.ps1 test           Python tests, in parallel (pytest -n auto)
#   .\dev.ps1 test-web       frontend unit tests (node --test)
#   .\dev.ps1 test-browser   Playwright browser tests (builds the UI first)
#   .\dev.ps1 lint           ruff + mypy + eslint
#   .\dev.ps1 check          everything CI runs (minus docker build)
#   .\dev.ps1 cli <args...>  pass through to the doblarr CLI
#
# Examples:
#   .\dev.ps1 cli check
#   .\dev.ps1 cli dub movie.mkv --to es --dry-run

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Prefer the project venv if it exists, else fall back to system python.
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Block
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ---- validate: one line per check, details only when it fails --------------

# Runs a native command with its stderr folded into the output, without
# Windows PowerShell turning a stderr line into a terminating error.
function Invoke-Quiet([scriptblock]$Block) {
    $saved = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $out = & $Block 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
    return @{ Out = @($out); Code = $LASTEXITCODE }
}

function Write-Check([string]$Name, [string]$State, [string]$Summary = "", [string[]]$Detail = @()) {
    $colour = @{ ok = "Green"; fixed = "Yellow"; fail = "Red" }[$State]
    Write-Host ("  {0,-16}" -f $Name) -ForegroundColor Cyan -NoNewline
    Write-Host ($(if ($Summary) { "$State ($Summary)" } else { $State })) -ForegroundColor $colour
    $Detail | Select-Object -First 25 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if ($State -eq "fail") { $script:Failures++ }
}

function Test-Ruff {
    $r = Invoke-Quiet { & $Python -m ruff check . }
    if ($r.Code -eq 0) { Write-Check "ruff" "ok"; return }
    # Safe fixes only; the repo deliberately does not run `ruff format`.
    $fix = Invoke-Quiet { & $Python -m ruff check . --fix }
    $found = ($r.Out | Select-String "^Found (\d+) error").Matches.Groups[1].Value
    if ($fix.Code -eq 0) { Write-Check "ruff" "fixed" "$found issues" }
    else { Write-Check "ruff" "fail" ($fix.Out | Select-String "^Found .*").Line ($fix.Out | Where-Object { $_ -match "^\S+:\d+:\d+: |-->" }) }
}

function Test-Mypy {
    $r = Invoke-Quiet { & $Python -m mypy doblarr/ }
    if ($r.Code -eq 0) { Write-Check "mypy" "ok"; return }
    Write-Check "mypy" "fail" ($r.Out | Select-String "^Found \d+ error").Line ($r.Out | Where-Object { $_ -match "error:" })
}

function Test-Pytest {
    # The fast tier: tests that render real audio end to end are marked slow
    # (tests/conftest.py) and run in `check` and CI.
    $r = Invoke-Quiet { & $Python -m pytest -q -n auto -m "not slow" --tb=line }
    $last = ($r.Out | Where-Object { $_ -match "\d+ (passed|failed|error)" } | Select-Object -Last 1) -replace "=", ""
    if ($r.Code -eq 0) { Write-Check "pytest" "ok" "$last".Trim(); return }
    Write-Check "pytest" "fail" "$last".Trim() ($r.Out | Where-Object { $_ -match "^(FAILED|ERROR) |^[A-Za-z]:\\.*:\d+: " })
}

function Test-Eslint {
    $r = Invoke-Quiet { npm run lint --silent }
    if ($r.Code -eq 0) { Write-Check "eslint" "ok"; return }
    Write-Check "eslint" "fail" ($r.Out | Select-String "problems?").Line ($r.Out | Where-Object { $_ -match "\S" -and $_ -notmatch "^>" })
}

function Test-NodeTests {
    $r = Invoke-Quiet { npm test --silent }
    $pass = ($r.Out | Select-String "^# pass (\d+)").Matches.Groups[1].Value
    if ($r.Code -eq 0) { Write-Check "node tests" "ok" "$pass passed"; return }
    Write-Check "node tests" "fail" ($r.Out | Select-String "^# fail \d+").Line ($r.Out | Where-Object { $_ -match "^not ok|AssertionError|Error:" })
}

function Test-Build {
    $r = Invoke-Quiet { npm run build:ui --silent }
    if ($r.Code -eq 0) { Write-Check "ui build" "ok"; return }
    Write-Check "ui build" "fail" "" ($r.Out | Where-Object { $_ -match "error|Error|\.jsx?:\d+" })
}

function Invoke-Validate([bool]$CheckPython, [bool]$CheckUi) {
    $script:Failures = 0
    $started = Get-Date
    $what = @(); if ($CheckPython) { $what += "Python" }; if ($CheckUi) { $what += "UI" }
    Write-Host ("[{0}] " -f $started.ToString("HH:mm:ss")) -ForegroundColor DarkGray -NoNewline
    Write-Host ("Checking " + ($what -join " + ")) -ForegroundColor Cyan
    if ($CheckPython) { Test-Ruff; Test-Mypy }
    if ($CheckUi) { Test-Eslint; Test-NodeTests; Test-Build }
    if ($CheckPython) { Test-Pytest }
    $took = [int]((Get-Date) - $started).TotalSeconds
    if ($script:Failures) { Write-Host "  $($script:Failures) failing · ${took}s" -ForegroundColor Red }
    else { Write-Host "  all good · ${took}s" -ForegroundColor Green }
    Write-Host ""
}

# Which side of the project a changed path belongs to, or $null to ignore it.
function Get-Side([string]$Path) {
    if ($Path -match "\\(node_modules|dist(-[^\\]*)?|__pycache__|\.mypy_cache|\.pytest_cache|test-results)(\\|$)") { return $null }
    if ($Path -match "\\ui\\|\\tests\\frontend\\") { return "ui" }
    if ($Path -match "\.py$") { return "python" }
    return $null
}

function Start-Validate {
    $dirs = @("doblarr", "tests", "ui") | ForEach-Object { Join-Path $PSScriptRoot $_ }
    Write-Host "[dev] Watching for lint + type + test errors (Python + UI)" -ForegroundColor Cyan
    $dirs | ForEach-Object { Write-Host "[dev]   $_" -ForegroundColor DarkGray }
    Write-Host "[dev] Slow end-to-end tests run in .\dev.ps1 check. Press Ctrl+C to stop." -ForegroundColor DarkGray
    Write-Host ""
    Invoke-Validate $true $true

    $queue = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    $watchers = @(); $subscriptions = @()
    foreach ($dir in $dirs) {
        $w = [System.IO.FileSystemWatcher]::new($dir)
        $w.IncludeSubdirectories = $true
        $w.NotifyFilter = [System.IO.NotifyFilters]'LastWrite, FileName'
        $w.EnableRaisingEvents = $true
        $watchers += $w
        foreach ($kind in "Changed", "Created", "Deleted", "Renamed") {
            $subscriptions += Register-ObjectEvent $w $kind -MessageData $queue -Action {
                $Event.MessageData.Enqueue($EventArgs.FullPath)
            }
        }
    }
    try {
        while ($true) {
            Start-Sleep -Milliseconds 400
            if ($queue.IsEmpty) { continue }
            # Debounce: an editor's save (or a branch switch) arrives as a burst.
            do { $before = $queue.Count; Start-Sleep -Milliseconds 700 } while ($queue.Count -ne $before)
            $sides = @{}
            $path = $null
            while ($queue.TryDequeue([ref]$path)) { $side = Get-Side $path; if ($side) { $sides[$side] = $true } }
            if (-not $sides.Count) { continue }
            Invoke-Validate ([bool]$sides["python"]) ([bool]$sides["ui"])
            # What the checks wrote themselves (ruff fixes, the UI build) is not a new change.
            while ($queue.TryDequeue([ref]$path)) { }
        }
    } finally {
        $subscriptions | ForEach-Object { Unregister-Event -SourceIdentifier $_.Name -ErrorAction SilentlyContinue }
        $watchers | ForEach-Object { $_.Dispose() }
    }
}

switch ($Command) {
    "setup" {
        Invoke-Step "pip install -e .[dev]" { & $Python -m pip install -e ".[dev]" }
        Invoke-Step "npm ci" { npm ci }
        Invoke-Step "playwright install chromium" { npx playwright install chromium }
    }
    "serve" {
        Invoke-Step "build web UI" { npm run build:ui }
        & $Python -m doblarr serve @Rest
    }
    "ui" {
        npm run dev:ui
    }
    "validate" {
        if ($Rest -contains "once") {
            Invoke-Validate $true $true
            exit $(if ($script:Failures) { 1 } else { 0 })
        }
        Start-Validate
    }
    "test" {
        & $Python -m pytest -q -n auto @Rest
        exit $LASTEXITCODE
    }
    "test-web" {
        npm test
        exit $LASTEXITCODE
    }
    "test-browser" {
        npm run test:browser -- @Rest
        exit $LASTEXITCODE
    }
    "lint" {
        Invoke-Step "ruff" { & $Python -m ruff check . }
        Invoke-Step "mypy" { & $Python -m mypy doblarr/ }
        Invoke-Step "eslint" { npm run lint }
    }
    "check" {
        Invoke-Step "ruff" { & $Python -m ruff check . }
        Invoke-Step "mypy" { & $Python -m mypy doblarr/ }
        Invoke-Step "pytest" { & $Python -m pytest -q -n auto --cov=doblarr --cov-report=term-missing --cov-fail-under=70 }
        Invoke-Step "npm run check" { npm run check }
        Write-Host "`nAll checks passed." -ForegroundColor Green
    }
    "cli" {
        & $Python -m doblarr @Rest
        exit $LASTEXITCODE
    }
    default {
        Get-Content $PSCommandPath -TotalCount 17
    }
}
