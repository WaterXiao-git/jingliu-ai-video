param([string]$Executable, [string]$Preview)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$icon = [Drawing.Icon]::ExtractAssociatedIcon([IO.Path]::GetFullPath($Executable))
if (!$icon) { throw 'EXE 没有可用图标' }
$bitmap = $icon.ToBitmap()
try {
    $colored = 0
    $transparent = 0
    for ($y = 0; $y -lt $bitmap.Height; $y++) {
        for ($x = 0; $x -lt $bitmap.Width; $x++) {
            $pixel = $bitmap.GetPixel($x, $y)
            if ($pixel.A -eq 0) { $transparent++ }
            $maximum = [math]::Max($pixel.R, [math]::Max($pixel.G, $pixel.B))
            $minimum = [math]::Min($pixel.R, [math]::Min($pixel.G, $pixel.B))
            if ($pixel.A -gt 100 -and ($maximum - $minimum) -gt 30) { $colored++ }
        }
    }
    if ($colored -lt ($bitmap.Width * $bitmap.Height / 5) -or $transparent -eq 0) {
        throw 'EXE 图标缺少预期彩色内容或透明通道'
    }
    if ($Preview) { $bitmap.Save([IO.Path]::GetFullPath($Preview), [Drawing.Imaging.ImageFormat]::Png) }
    @{width=$bitmap.Width; height=$bitmap.Height; colored_pixels=$colored; transparent_pixels=$transparent} | ConvertTo-Json -Compress
} finally { $bitmap.Dispose(); $icon.Dispose() }
