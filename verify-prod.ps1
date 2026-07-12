<#
.SYNOPSIS
  Run the production smoke tests (API shape + email-digest dry-run) and the
  Playwright e2e journeys against the live site. Run this after a deploy has
  finished - it hits prod, so it needs no local backend or frontend running.

.DESCRIPTION
  Mirrors the scheduled `smoke` and `e2e` GitHub workflows, but on-demand so you
  can verify a session's worth of pushes with one command instead of a CI run
  per push.

  The digest dry-run check runs only if $env:DIGEST_CRON_TOKEN is set to the
  real backend token; otherwise it is skipped (never sends email).

.EXAMPLE
  ./verify-prod.ps1                     # smoke + e2e against prod
  ./verify-prod.ps1 -SkipE2e            # API smoke only (~10s)
  ./verify-prod.ps1 -SkipSmoke          # browser e2e only
  $env:DIGEST_CRON_TOKEN='...'; ./verify-prod.ps1   # include digest dry-run
#>
param(
    [switch]$SkipSmoke,
    [switch]$SkipE2e
)

$root = $PSScriptRoot
$failed = $false

if (-not $SkipSmoke) {
    Write-Host "`n=== Smoke: API shape vs prod ===" -ForegroundColor Cyan
    if (-not $env:DIGEST_CRON_TOKEN) {
        Write-Host "  (DIGEST_CRON_TOKEN not set - digest dry-run test will be skipped)" -ForegroundColor DarkGray
    }
    Push-Location (Join-Path $root 'backend')
    try {
        python -m pytest smoke
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    } finally { Pop-Location }
}

if (-not $SkipE2e) {
    Write-Host "`n=== Playwright e2e vs prod ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    try {
        npx playwright test
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    } finally { Pop-Location }
}

if ($failed) {
    Write-Host "`nFAILED - see output above." -ForegroundColor Red
    exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green
