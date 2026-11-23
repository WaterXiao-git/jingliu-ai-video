param([Parameter(Mandatory=$true)][string] $InputFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$request = Get-Content -LiteralPath $InputFile -Raw -Encoding UTF8 | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @($synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' -and
        $_.VoiceInfo.Gender.ToString() -eq $request.gender
    })
    if (!$voices.Count) { throw '未安装对应的中文系统声线，请在 Windows 语音设置中添加中文语音，或上传项目音轨。' }
    $synth.SelectVoice($voices[0].VoiceInfo.Name)
    $synth.SetOutputToWaveFile($request.output)
    $synth.Speak($request.text)
} finally { $synth.Dispose() }
