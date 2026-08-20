param(
    [string]$ProjectRoot = "C:\TradingbotR1000"
)

Set-Location -LiteralPath $ProjectRoot
python -m analytics.flex_analytics.cli validate-only
