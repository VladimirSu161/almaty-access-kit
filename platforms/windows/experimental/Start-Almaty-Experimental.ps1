# Старый путь совместимости: обычный launcher выполняет те же реальные проверки.
& (Join-Path $PSScriptRoot '../Start-Almaty.ps1') @args
exit $LASTEXITCODE
