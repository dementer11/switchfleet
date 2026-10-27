$ErrorActionPreference = 'Stop'
$runtime = $PSScriptRoot
$qemu = [System.IO.Path]::GetFullPath((Join-Path $runtime 'qemu\qemu-system-x86_64.exe'))
$dataDisk = [System.IO.Path]::GetFullPath((Join-Path $runtime 'data.qcow2'))
$pidFile = Join-Path $runtime 'switchfleet-qemu.pid'

if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'SwitchFleet VM is not running.'; exit 0 }
$qemuIdText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
if ($qemuIdText -notmatch '^\d+$') { throw 'QEMU PID file is invalid.' }
$qemuId = [int]$qemuIdText
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $qemuId" -ErrorAction SilentlyContinue
if (-not $process) { Remove-Item -LiteralPath $pidFile -Force; Write-Output 'SwitchFleet VM was already stopped.'; exit 0 }
if (-not [System.String]::Equals([System.IO.Path]::GetFullPath($process.ExecutablePath), $qemu, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'PID file does not refer to the packaged QEMU binary; refusing to contact an unrelated process.'
}
if (-not ($process.CommandLine.Contains($dataDisk) -or $process.CommandLine.Contains('file=./data.qcow2,if=virtio,format=qcow2'))) {
    throw 'Packaged QEMU is not using this runtime data.qcow2; refusing to stop it.'
}
$qmpListener = Get-NetTCPConnection -State Listen -LocalPort 18788 -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $qemuId
if (-not $qmpListener) { throw 'Packaged QEMU does not own the expected loopback QMP listener; refusing to stop it.' }

$client = New-Object System.Net.Sockets.TcpClient
try {
    $client.ReceiveTimeout = 5000
    $client.SendTimeout = 5000
    $client.Connect('127.0.0.1', 18788)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)))
    $writer.AutoFlush = $true
    $greeting = $reader.ReadLine()
    if (-not $greeting -or $greeting -notmatch '"QMP"') { throw 'QMP handshake failed.' }
    $writer.WriteLine('{"execute":"qmp_capabilities"}')
    $capabilityReply = $reader.ReadLine()
    if (-not $capabilityReply -or $capabilityReply -notmatch '"return"') { throw 'QMP capability negotiation failed.' }
    $writer.WriteLine('{"execute":"system_powerdown"}')
} finally {
    if ($client) { $client.Close() }
}

for ($attempt = 0; $attempt -lt 45; $attempt++) {
    if (-not (Get-Process -Id $qemuId -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        Write-Output 'SwitchFleet VM stopped cleanly through QMP.'
        exit 0
    }
    Start-Sleep -Seconds 2
}
throw 'QEMU is still running after QMP powerdown; inspect the serial log and retain data.qcow2.'
