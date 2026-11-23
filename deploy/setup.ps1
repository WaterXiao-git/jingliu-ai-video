[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Check', 'Plan', 'Install', 'Start', 'Verify')]
    [string] $Mode = 'Menu',
    [string] $Target,
    [string] $ReuseComfy,
    [string] $Python,
    [string] $Region,
    [switch] $WithOllama,
    [switch] $Video,
    [switch] $AllowPythonBootstrap,
    [string] $PlanFile,
    [string] $Approve,
    [switch] $NoStart,
    [int] $Port = 7861
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$root = Split-Path -Parent $PSScriptRoot
if (!$Target) { $Target = Join-Path $root '.runtime' }
$Target = [IO.Path]::GetFullPath($Target)
$spec = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'deploy-spec.yaml') -Raw -Encoding UTF8 | ConvertFrom-Json
$configPath = Join-Path $Target 'runtime.json'

function Find-Python {
    $paths = @()
    if ($Python) { $paths += $Python }
    if (Test-Path -LiteralPath $configPath) {
        $paths += (Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json).python
    }
    if ($ReuseComfy) { $paths += (Join-Path $ReuseComfy '.venv\Scripts\python.exe') }
    $paths += (Join-Path $Target 'python311\python.exe')
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython -and $pathPython.Source -notlike '*\Microsoft\WindowsApps\*') { $paths += $pathPython.Source }
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $registrations = & py.exe -0p 2>$null
        foreach ($line in $registrations) {
            if ($line -match '3\.11(?:-64)?\s+\*?\s*(.+\\python\.exe)\s*$') { $paths += $Matches[1].Trim() }
        }
    }
    foreach ($candidate in ($paths | Select-Object -Unique)) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $version = & $candidate -B -c 'import sys,struct;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1])+chr(32)+str(struct.calcsize(chr(80))))'
            if ($LASTEXITCODE -eq 0 -and $version -eq '3.11 8') { return $candidate }
        }
    }
    return $null
}

function Show-BootstrapCheck {
    $system = Get-CimInstance Win32_OperatingSystem
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Target))
    $gib = [math]::Round(($drive.AvailableFreeSpace / 1GB), 2)
    $ram = [math]::Round(($system.TotalVisibleMemorySize / 1MB), 2)
    $expected = if ($ReuseComfy) { $spec.budgets.reuse_runtime_gib } else { $spec.budgets.fresh_runtime_gib }
    if ($WithOllama) { $expected += 10 }
    Write-Host "Windows $($system.OSArchitecture) · 内存 $ram GiB · 目标磁盘剩余 $gib GiB，建议 $expected GiB。"
    $cards = @()
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($smi) {
        $cards = & $smi.Source --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits
        $cards | ForEach-Object { Write-Host "NVIDIA（名称 / 总显存 MiB / 空闲 MiB / 驱动）：$_" }
    }
    $vramOk = $false
    foreach ($card in $cards) {
        $parts = $card.Split(',') | ForEach-Object Trim
        if ($parts.Count -ge 4 -and $parts[1] -match '^\d+$' -and $parts[2] -match '^\d+$' -and
            $parts[3] -match '^(\d+)\.' -and [int]$Matches[1] -ge $spec.platform.driver_major_floor -and
            [int]$parts[1] -ge $spec.platform.minimum_vram_mib -and [int]$parts[2] -ge $spec.platform.minimum_free_vram_mib) {
            $vramOk = $true
        }
    }
    if (!$vramOk -or $ram -lt $spec.platform.minimum_ram_gib -or $gib -lt $expected -or
        $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
        Write-Host '当前未达到安装预检条件。请释放资源、换盘，或考虑以下云端选项。'
        $alternatives = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'platforms.yaml') -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in $alternatives.platforms) { Write-Host "$($item.name) · $($item.url)" }
        return $false
    }
    return $true
}

function Download-Bootstrap([string] $Url, [string] $Destination) {
    $uri = [Uri]$Url
    for ($redirect = 0; $redirect -lt 10; $redirect++) {
        $allowed = $spec.download_hosts | Where-Object { $uri.Host -eq $_ -or $uri.Host.EndsWith('.' + $_) }
        if ($uri.Scheme -ne 'https' -or !$allowed) { throw "下载地址不在国内分发清单中：$($uri.Host)" }
        @{event='request'; host=$uri.Host; path=$uri.AbsolutePath} | ConvertTo-Json -Compress |
            Add-Content -LiteralPath (Join-Path $Target 'bootstrap-network.jsonl') -Encoding UTF8
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'Jingliu-Installer/' + $spec.version
        $request.Timeout = 60000
        $response = $null
        try {
            $response = $request.GetResponse()
            if ([int]$response.StatusCode -in 301,302,303,307,308) {
                $uri = [Uri]::new($uri, $response.Headers['Location'])
                continue
            }
            if ([int]$response.StatusCode -ne 200) { throw "Python 下载状态异常：$($response.StatusCode)" }
            $inputStream = $response.GetResponseStream()
            $outputStream = [IO.File]::Create($Destination)
            try { $inputStream.CopyTo($outputStream) }
            finally { $outputStream.Dispose(); $inputStream.Dispose() }
            return
        } finally {
            if ($response) { $response.Dispose() }
        }
    }
    throw 'Python 下载跳转次数过多。'
}

function Install-PrivatePython {
    $package = $spec.python_bootstrap
    $downloads = Join-Path $Target 'downloads'
    $destination = Join-Path $Target 'python311'
    $installer = Join-Path $downloads 'python.3.11.9.nupkg'
    if ((Test-Path -LiteralPath $destination) -and !(Test-Path -LiteralPath (Join-Path $destination 'python.exe'))) {
        throw '目标目录里已有未完成的 Python 安装。请检查该目录或使用新的 -Target。'
    }
    Write-Host "将下载 Python 官方 NuGet 包（3.11.9 x64，约 18 MB），解压到 $destination"
    if (!$AllowPythonBootstrap -and (Read-Host '输入 YES 同意部署此独立 Python') -cne 'YES') { throw '已取消 Python 部署。' }
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    if (!(Test-Path -LiteralPath $installer)) {
        $part = "$installer.part"
        Download-Bootstrap $package.url $part
        if ((Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash -ne $package.sha256) { throw 'Python 安装包校验失败。' }
        Move-Item -LiteralPath $part -Destination $installer
    }
    if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $package.sha256) { throw 'Python 安装包校验失败。' }
    $stage = Join-Path $Target ('.python311.extract-' + $PID)
    if (Test-Path -LiteralPath $stage) { throw 'Python 临时解压目录已存在，请检查后重试。' }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($installer, $stage)
        if (!(Test-Path -LiteralPath (Join-Path $stage 'tools\python.exe'))) { throw 'Python 包缺少可执行文件。' }
        Move-Item -LiteralPath (Join-Path $stage 'tools') -Destination $destination
    } finally {
        $absoluteStage = [IO.Path]::GetFullPath($stage)
        if (!$absoluteStage.StartsWith($Target.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Python 临时目录不在安装目标内。'
        }
        if (Test-Path -LiteralPath $absoluteStage) { Remove-Item -LiteralPath $absoluteStage -Recurse -Force }
    }
    return (Join-Path $destination 'python.exe')
}

try {
    if ($Mode -eq 'Menu') {
        if (Test-Path -LiteralPath $configPath) { $Mode = 'Start' }
        else {
            Write-Host '镜流首次启动'
            Write-Host '1  检查这台电脑'
            Write-Host '2  检查并安装'
            $choice = Read-Host '请选择 1 或 2'
            if ($choice -eq '1') { $Mode = 'Check' }
            elseif ($choice -eq '2') { $Mode = 'Install' }
            else { exit 0 }
            if ($Mode -eq 'Install' -and !$WithOllama) {
                $WithOllama = (Read-Host '同时安装本地 AI 编剧（多约 6.3 GB 下载）？输入 y 同意') -eq 'y'
            }
        }
    }
    $entry = Find-Python
    if (!$entry) {
        if ($Mode -notin 'Check', 'Plan', 'Install') { throw '未找到 Python 3.11 x64。请先运行安装。' }
        $suitable = Show-BootstrapCheck
        if ($Mode -eq 'Check') { Write-Host '这是 PowerShell 初检。安装时会执行更完整的 Doctor 检查。'; exit 0 }
        if (!$suitable) { exit 1 }
        if ($Mode -eq 'Plan') {
            if (!$AllowPythonBootstrap) { throw '生成安装计划需要 Python，请明确允许准备独立 Python 后重试。' }
            $entry = Install-PrivatePython
        }
    }
    if ($Mode -eq 'Install') {
        Write-Host "请阅读 MiniMax H3 社区许可：$($spec.license.url)"
        if (!$Region) { $Region = Read-Host '请输入你实际使用模型的地区代码，例如中国大陆 CN' }
        $Region = $Region.Trim().ToUpperInvariant()
        if ($Region -notmatch '^[A-Z]{2}$' -or $Region -in $spec.license.excluded -or $Region -in 'XX','ZZ','UN','AA') {
            throw '当前地区声明无法用于 H3 安装。可在 deploy/platforms.yaml 查看云端选项。'
        }
        if (!$entry) { $entry = Install-PrivatePython }
    }
    $tool = Join-Path $PSScriptRoot 'installer.py'
    $arguments = @('--target', $Target, '--port', "$Port")
    if ($ReuseComfy) { $arguments += @('--reuse-comfy', $ReuseComfy) }
    if ($WithOllama) { $arguments += '--with-ollama' }
    if ($Region) { $arguments += @('--region', $Region) }
    switch ($Mode) {
        Plan {
            if (!$PlanFile) { throw '请指定安装计划输出文件 -PlanFile。' }
            $planText = & $entry -B $tool plan @arguments --json
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            $planText = $planText -join [Environment]::NewLine
            $null = $planText | ConvertFrom-Json
            $planPath = [IO.Path]::GetFullPath($PlanFile)
            New-Item -ItemType Directory -Path (Split-Path $planPath -Parent) -Force | Out-Null
            [IO.File]::WriteAllText($planPath, $planText, [Text.UTF8Encoding]::new($false))
            Write-Host "检测与安装计划已保存：$planPath"
            exit 0
        }
        Check {
            & $entry -B $tool plan @arguments
            exit $LASTEXITCODE
        }
        Install {
            $installArguments = @($arguments)
            if ($Approve) { $installArguments += @('--approve', $Approve) }
            & $entry -B $tool install @installArguments
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & $entry -B $tool verify --target $Target --video
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            if ($NoStart) { exit 0 }
            & (Join-Path $PSScriptRoot 'launch.ps1') -Target $Target
            exit $LASTEXITCODE
        }
        Verify {
            $verifyArgs = @('--target', $Target)
            if ($Video) { $verifyArgs += '--video' }
            & $entry -B $tool verify @verifyArgs
            exit $LASTEXITCODE
        }
        Start {
            & (Join-Path $PSScriptRoot 'launch.ps1') -Target $Target
            exit $LASTEXITCODE
        }
    }
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
