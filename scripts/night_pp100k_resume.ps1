param(
    [Parameter(Mandatory = $true)]
    [int]$Seed,
    [Parameter(Mandatory = $true)]
    [string]$RunGroup,
    [int]$Cases = 10000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$reportsRoot = "reports/ath_experiments"
$logPath = Join-Path $reportsRoot "night_pp100k.log"
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

function Write-RunLog {
    param(
        [string]$Message
    )
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$stamp] $Message"
    Write-Host $line
    Add-Content -Path $logPath -Value $line
}

try {
    $args = @(
        "-m", "app", "projectpage-ath-experiment",
        "--cases", "$Cases",
        "--seed", "$Seed",
        "--run-group", "$RunGroup",
        "--cfg-dir", "C:\Tools\ATH",
        "--export-root", "C:\Horns",
        "--reports-root", "reports/ath_experiments",
        "--hard-cap-mm", "5000",
        "--commit-every", "50",
        "--history-snapshots", "true",
        "--priors-path", "reports/ath_experiments/range_suggestions.v1.json",
        "--cleanup-files", "true",
        "--preclean-files", "false",
        "--cleanup-cases", "end",
        "--cleanup-log", "end"
    )

    Write-RunLog "START resume seed=$Seed run_group=$RunGroup cases=$Cases"
    & python @args
    $exitCode = $LASTEXITCODE
    Write-RunLog "END   resume seed=$Seed run_group=$RunGroup exit_code=$exitCode"
    if ($exitCode -ne 0) {
        throw "Resume run failed (exit=$exitCode)."
    }
    exit 0
}
catch {
    Write-RunLog "FAILED resume: $($_.Exception.Message)"
    exit 1
}
