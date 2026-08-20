$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BotDir = Join-Path $ProjectRoot "current_reference\PaperTradingR1000"
$StateDir = Join-Path $BotDir "state"

Write-Host "TradingbotR1000 status"
Write-Host "Project: $ProjectRoot"
Write-Host "Bot dir: $BotDir"

foreach ($name in @("runtime_health.json", "heartbeat.json", "bot_status.json", "controller_status.json", "health_supervisor_status.json", "startup_validation.json")) {
    $path = Join-Path $StateDir $name
    if (Test-Path -LiteralPath $path) {
        Write-Host ""
        Write-Host "[$name]"
        Get-Content -LiteralPath $path
    } else {
        Write-Host "$name: missing"
    }
}
