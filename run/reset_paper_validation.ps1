$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BotDir = Join-Path $ProjectRoot "current_reference\PaperTradingR1000"
Write-Host "Paper-validation reset target: $BotDir"
Write-Host "Remove generated state/log/report files only after explicit operator approval."
