Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Unable to resolve the repository root."
}

Push-Location $repoRoot
try {
    git config --local core.hooksPath .githooks
    Write-Host "Configured local git hooks path: .githooks" -ForegroundColor Green
    Write-Host "Hooks are now repo-scoped and will run the shared quality gate." -ForegroundColor Green
}
finally {
    Pop-Location
}
