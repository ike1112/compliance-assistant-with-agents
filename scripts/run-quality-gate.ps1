param(
    [string]$Hook = "manual"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ") -ForegroundColor DarkGray
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

function Invoke-OptionalSonar {
    $enabled = $env:ENABLE_SONAR_HOOK
    if ($enabled -notin @("1", "true", "TRUE", "True")) {
        Write-Host ""
        Write-Host "==> Sonar step skipped (set ENABLE_SONAR_HOOK=1 to enable)." -ForegroundColor Yellow
        return
    }

    $scanner = Get-Command sonar-scanner -ErrorAction SilentlyContinue
    if (-not $scanner) {
        throw "ENABLE_SONAR_HOOK is set but sonar-scanner is not installed."
    }

    if (-not (Test-Path "sonar-project.properties")) {
        throw "ENABLE_SONAR_HOOK is set but sonar-project.properties is missing."
    }

    Invoke-Step -Name "Run Sonar scanner" -Command @("sonar-scanner")
}

function Invoke-OptionalBandit {
    $enabled = $env:ENABLE_BANDIT_HOOK
    if ($enabled -notin @("1", "true", "TRUE", "True")) {
        Write-Host ""
        Write-Host "==> Bandit step skipped (set ENABLE_BANDIT_HOOK=1 to enable)." -ForegroundColor Yellow
        return
    }

    Invoke-Step -Name "Run Bandit" -Command @(
        "uv", "run", "--no-sync", "python", "-m", "bandit", "-q", "-r", "src", "infra/runtime", "infra/lambdas"
    )
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) {
    throw "Unable to resolve the repository root."
}

Push-Location $repoRoot
try {
    Write-Host "Running quality gate for $Hook from $repoRoot" -ForegroundColor Green

    Invoke-Step -Name "Verify locked dependencies" -Command @(
        "uv", "sync", "--frozen", "--extra", "infra", "--extra", "gate"
    )

    $env:PYTHONPATH = "src"

    Invoke-OptionalBandit

    Invoke-Step -Name "Run unit and integration tests" -Command @(
        "uv", "run", "--no-sync", "python", "-m", "pytest", "tests", "infra/tests", "-q"
    )

    Invoke-Step -Name "Run offline eval gate" -Command @(
        "uv", "run", "--no-sync", "python", "-m", "pytest", "tests/evals", "-m", "gate", "-q"
    )

    Push-Location "infra"
    try {
        Invoke-Step -Name "Synthesize CDK templates" -Command @(
            "npx", "--yes", "aws-cdk@latest", "synth", "ComplianceObservabilityStack",
            "ComplianceKbStack", "ComplianceAgentStack", "ComplianceRuntimeEcrStack",
            "ComplianceRuntimeStack", "-q"
        )
    }
    finally {
        Pop-Location
    }

    $templates = @(
        "infra/cdk.out/ComplianceKbStack.template.json",
        "infra/cdk.out/ComplianceAgentStack.template.json",
        "infra/cdk.out/ComplianceRuntimeEcrStack.template.json",
        "infra/cdk.out/ComplianceRuntimeStack.template.json",
        "infra/cdk.out/ComplianceObservabilityStack.template.json"
    )
    foreach ($template in $templates) {
        Invoke-Step -Name "cfn-lint $template" -Command @(
            "uv", "run", "--no-sync", "cfn-lint", "--non-zero-exit-code", "error", "-r", "us-east-1", "-t", $template
        )
    }

    Invoke-OptionalSonar

    Write-Host ""
    Write-Host "Quality gate passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
