param(
    [string]$Target = (Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'),
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
try {
    $Target = [IO.Path]::GetFullPath($Target)
    $configPath = Join-Path $Target 'runtime.json'
    if (!(Test-Path -LiteralPath $configPath)) {
        if ($Stop) { exit 0 }
        Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\setup.ps1`" -Target `"$Target`""
        exit 0
    }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (!(Test-Path -LiteralPath $config.python)) { throw '找不到已部署的 Python，请重新运行部署检查。' }
    $arguments = "-B `"$PSScriptRoot\launcher.py`" --target `"$Target`""
    if ($Stop) { $arguments += ' --stop' }
    # No activation, package probing or model downloads on the daily launch path.
    Start-Process -FilePath $config.python -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory (Split-Path $PSScriptRoot -Parent)
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, '镜流启动失败') | Out-Null
    exit 1
}
