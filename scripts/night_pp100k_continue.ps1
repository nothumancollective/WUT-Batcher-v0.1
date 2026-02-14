param(
    [int]$StartSeed = 2101,
    [int]$EndSeed = 2109,
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
    if ($StartSeed -gt $EndSeed) {
        throw "StartSeed must be <= EndSeed."
    }

    for ($seed = $StartSeed; $seed -le $EndSeed; $seed++) {
        $runGroup = "pp100k_$seed"
        Write-RunLog "START continue seed=$seed run_group=$runGroup"
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\night_pp100k_resume.ps1 -Seed $seed -RunGroup $runGroup -Cases $Cases
        $exitCode = $LASTEXITCODE
        Write-RunLog "END   continue seed=$seed run_group=$runGroup exit_code=$exitCode"
        if ($exitCode -ne 0) {
            throw "Continue block failed for run_group=$runGroup (exit=$exitCode)."
        }
    }

    $runGroups = @()
    for ($seed = 2100; $seed -le $EndSeed; $seed++) {
        $runGroups += "pp100k_$seed"
    }
    $aggregateArg = [string]::Join(",", $runGroups)
    $aggTs = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $aggRunGroup = "pp100k_aggregate_$aggTs"
    Write-RunLog "START continue aggregation run_group=$aggRunGroup groups=$aggregateArg"
    & python -m app projectpage-ath-experiment --cases 0 --seed 0 --run-group $aggRunGroup --aggregate-run-groups $aggregateArg --cfg-dir C:\Tools\ATH --export-root C:\Horns --reports-root reports/ath_experiments --cleanup-files false --preclean-files false --cleanup-cases never --cleanup-log never --history-snapshots true --priors-path reports/ath_experiments/range_suggestions.v1.json | Out-Host
    $aggExit = $LASTEXITCODE
    Write-RunLog "END   continue aggregation run_group=$aggRunGroup exit_code=$aggExit"
    if ($aggExit -ne 0) {
        throw "Continue aggregation failed (exit=$aggExit)."
    }

    Write-RunLog "Continue run completed successfully."
    exit 0
}
catch {
    Write-RunLog "FAILED continue: $($_.Exception.Message)"
    exit 1
}
