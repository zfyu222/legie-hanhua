param([Parameter(Mandatory)][ValidateSet('Install','Uninstall')][string]$Action)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'delta.json') | ConvertFrom-Json
$backup = Join-Path $root '.zfy-legie-original'
$decoder = Join-Path $PSScriptRoot 'xdelta3.exe'
function Hash([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($Path))
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try { return [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '') }
        finally { $stream.Dispose(); $sha256.Dispose() }
    }
}
$gamePath = Join-Path $root 'legie.exe'
if (-not (Test-Path -LiteralPath $gamePath -PathType Leaf)) { throw '请将补丁解压到 legie.exe 所在文件夹。' }
if (Get-Process -Name legie -ErrorAction SilentlyContinue) { throw '请先退出 LEGIE，再运行此脚本。' }
if ((Hash $decoder) -ne $manifest.decoder_sha256) { throw '差分工具校验失败，请重新解压。' }
$names = @('legie.exe', 'legie.sud')
$records = @{}
foreach ($row in $manifest.files) {
    if ($row.name -notin $names -or $records.ContainsKey($row.name)) { throw '文件清单不正确。' }
    $records[$row.name] = $row
}
if ($records.Count -ne $names.Count) { throw '文件清单不完整。' }

$scratch = Join-Path $root ('.zfy-legie-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
$changed = [Collections.Generic.List[string]]::new()
$prepared = @{}
try {
    foreach ($name in $names) {
        $row = $records[$name]
        $target = Join-Path $root $name
        $saved = Join-Path $backup $name
        $current = Hash $target
        $wanted = if ($Action -eq 'Install') { $row.patched } else { $row.original }
        if ($current -eq $wanted) { continue }
        $out = Join-Path $scratch $name
        if ($Action -eq 'Uninstall') {
            if (($current -and $current -ne $row.patched) -or (Hash $saved) -ne $row.original) {
                throw "无法恢复 $name，请通过 Steam 验证游戏文件完整性。"
            }
            Copy-Item -LiteralPath $saved -Destination $out
        } else {
            if ($current -eq $row.original) { $base = $target }
            elseif ((-not $current -or $current -in $row.legacy) -and (Hash $saved) -eq $row.original) { $base = $saved }
            else { throw "不支持当前的 $name，请通过 Steam 验证游戏文件完整性。" }
            $patch = Join-Path $PSScriptRoot "..\汉化文件\$name.vcdiff"
            if ((Hash $patch) -ne $row.delta_sha256) { throw '补丁文件校验失败，请重新解压。' }
            # The decoder receives ASCII arguments even in Unicode Steam libraries.
            Copy-Item -LiteralPath $base -Destination (Join-Path $scratch "$name.original")
            Copy-Item -LiteralPath $patch -Destination (Join-Path $scratch "$name.vcdiff")
            $child = Start-Process -FilePath $decoder -WorkingDirectory $scratch -WindowStyle Hidden -ArgumentList @('-d', '-s', "$name.original", "$name.vcdiff", $name) -Wait -PassThru
            if ($child.ExitCode -ne 0) { throw "无法生成 $name。" }
            $prepared[$name] = $base
        }
        if ((Hash $out) -ne $wanted) { throw "生成文件校验失败：$name。" }
    }

    if ($Action -eq 'Install' -and $prepared.Count) {
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        foreach ($name in $prepared.Keys) {
            $saved = Join-Path $backup $name
            if (-not (Test-Path -LiteralPath $saved)) { Copy-Item -LiteralPath $prepared[$name] -Destination $saved }
            if ((Hash $saved) -ne $records[$name].original) { throw "原版备份校验失败：$name。" }
        }
    }
    foreach ($name in $names) {
        $out = Join-Path $scratch $name
        if (-not (Test-Path -LiteralPath $out)) { continue }
        $target = Join-Path $root $name
        if (Test-Path -LiteralPath $target) { [IO.File]::Replace($out, $target, "$out.before") }
        else { [IO.File]::Move($out, $target) }
        $changed.Add($name)
        $wanted = if ($Action -eq 'Install') { $records[$name].patched } else { $records[$name].original }
        if ((Hash $target) -ne $wanted) { throw "写入后校验失败：$name。" }
    }
} catch {
    foreach ($name in $changed) {
        $previous = Join-Path $scratch "$name.before"
        $target = Join-Path $root $name
        if (Test-Path -LiteralPath $previous) { [IO.File]::Replace($previous, $target, $null) }
        else { Remove-Item -LiteralPath $target }
    }
    throw
} finally {
    Get-ChildItem -LiteralPath $scratch -File | Remove-Item
    Remove-Item -LiteralPath $scratch
}
if ($Action -eq 'Install') { Write-Host '安装完成。请从 Steam 以英语语言选项启动游戏。' }
else { Write-Host '卸载完成。' }
