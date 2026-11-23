param([string]$Target = (Join-Path (Split-Path $PSScriptRoot -Parent) '.runtime'))
$ErrorActionPreference = 'Stop'
$Target = [IO.Path]::GetFullPath($Target)
if (!(Test-Path -LiteralPath (Join-Path $Target 'runtime.json'))) { throw '请先完成部署，再创建快捷方式。' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
foreach ($entry in @(@{Name='打开镜流';Extra=''}, @{Name='关闭镜流';Extra=' -Stop'})) {
    $launch = Join-Path $PSScriptRoot 'launch.ps1'
    $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launch`" -Target `"$Target`"$($entry.Extra)"
    $path = Join-Path $desktop "$($entry.Name).lnk"
    $suffix = 2
    while (Test-Path -LiteralPath $path) {
        $existing = $shell.CreateShortcut($path)
        if ($existing.Arguments -eq $arguments) { break }
        $path = Join-Path $desktop "$($entry.Name) ($suffix).lnk"
        $suffix++
    }
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $link.Arguments = $arguments
    $link.WorkingDirectory = Split-Path $PSScriptRoot -Parent
    $link.Description = '镜流本地 AI 短剧工作台'
    $link.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
    $link.Save()
    Write-Host "已创建：$path"
}
