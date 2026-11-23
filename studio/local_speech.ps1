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
# System voices append long pauses. Keep a short pause at each edge for dialogue timing.
$trimmed = $request.output + '.trim.wav'
$trim = 'silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB:start_silence=0.05,areverse'
& ffmpeg -v error -y -i $request.output -af $trim $trimmed
if ($LASTEXITCODE -ne 0) { throw '本地配音的首尾静音处理失败。' }
Move-Item -LiteralPath $trimmed -Destination $request.output -Force
