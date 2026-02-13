param()

$ErrorActionPreference = 'Stop'

Write-Host '[hooks] Setting core.hooksPath -> .githooks'
git config core.hooksPath .githooks

Write-Host '[hooks] Enabling push.autoSetupRemote=true'
git config push.autoSetupRemote true

Write-Host '[hooks] Setting push.default=current'
git config push.default current

Write-Host '[hooks] Done.'
