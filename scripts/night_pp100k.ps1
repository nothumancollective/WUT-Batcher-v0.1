param(
    [int]$CasesPerBlock = 10000
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

function Invoke-ExperimentBlock {
    param(
        [int]$Seed,
        [string]$RunGroup,
        [string]$PrecleanFiles
    )

    $args = @(
        "-m", "app", "projectpage-ath-experiment",
        "--cases", "$CasesPerBlock",
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
        "--preclean-files", "$PrecleanFiles",
        "--cleanup-cases", "end",
        "--cleanup-log", "end"
    )

    Write-RunLog "START block seed=$Seed run_group=$RunGroup preclean=$PrecleanFiles"
    & python @args | Out-Host
    $exitCode = $LASTEXITCODE
    Write-RunLog "END   block seed=$Seed run_group=$RunGroup exit_code=$exitCode"
    return [int]$exitCode
}

try {
    $seeds = 2100..2109
    $runGroups = @()
    foreach ($seed in $seeds) {
        $runGroup = "pp100k_$seed"
        $runGroups += $runGroup
        $preclean = if ($seed -eq 2100) { "true" } else { "false" }
        $code = Invoke-ExperimentBlock -Seed $seed -RunGroup $runGroup -PrecleanFiles $preclean
        if ($code -ne 0) {
            throw "Block failed for run_group=$runGroup (exit=$code). Resume with scripts/night_pp100k_resume.ps1."
        }
    }

    $aggTs = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $aggRunGroup = "pp100k_aggregate_$aggTs"
    $aggregateArg = [string]::Join(",", $runGroups)
    $aggArgs = @(
        "-m", "app", "projectpage-ath-experiment",
        "--cases", "0",
        "--seed", "0",
        "--run-group", "$aggRunGroup",
        "--aggregate-run-groups", "$aggregateArg",
        "--cfg-dir", "C:\Tools\ATH",
        "--export-root", "C:\Horns",
        "--reports-root", "reports/ath_experiments",
        "--cleanup-files", "false",
        "--preclean-files", "false",
        "--cleanup-cases", "never",
        "--cleanup-log", "never",
        "--history-snapshots", "true",
        "--priors-path", "reports/ath_experiments/range_suggestions.v1.json"
    )

    Write-RunLog "START aggregate run_group=$aggRunGroup groups=$aggregateArg"
    & python @aggArgs
    $aggExit = $LASTEXITCODE
    Write-RunLog "END   aggregate run_group=$aggRunGroup exit_code=$aggExit"
    if ($aggExit -ne 0) {
        throw "Aggregation failed (exit=$aggExit)."
    }

    Write-RunLog "Night run completed successfully."
    exit 0
}
catch {
    Write-RunLog "FAILED: $($_.Exception.Message)"
    exit 1
}
