$ErrorActionPreference = 'Stop'
$runtime = $PSScriptRoot
$qemu = Join-Path $runtime 'qemu\qemu-system-x86_64.exe'
$qemuImg = Join-Path $runtime 'qemu\qemu-img.exe'
$baseDisk = Join-Path $runtime 'switchfleet-v1.qcow2'
$dataDisk = Join-Path $runtime 'data.qcow2'
$pidFile = Join-Path $runtime 'switchfleet-qemu.pid'
$stdoutLog = Join-Path $runtime 'switchfleet-qemu.stdout.log'
$stderrLog = Join-Path $runtime 'switchfleet-qemu.stderr.log'
$serialLog = Join-Path $runtime 'switchfleet-qemu.serial.log'
$url = 'http://127.0.0.1:18787/'

function ConvertTo-WindowsCommandLineArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $backslashes++; continue }
        if ($character -eq '"') {
            if ($backslashes -gt 0) { [void]$builder.Append(('\' * (2 * $backslashes + 1))) }
            else { [void]$builder.Append('\') }
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) { [void]$builder.Append(('\' * $backslashes)); $backslashes = 0 }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) { [void]$builder.Append(('\' * (2 * $backslashes))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

foreach ($required in @($qemu, $qemuImg, (Join-Path $runtime 'qemu\share'), $baseDisk)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Portable runtime component is missing: $required" }
}
if (Test-Path -LiteralPath $pidFile) {
    $oldIdText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($oldIdText -match '^\d+$') {
        $oldId = [int]$oldIdText
        $oldProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $oldId" -ErrorAction SilentlyContinue
        if ($oldProcess) {
            $oldPathMatches = [System.String]::Equals([System.IO.Path]::GetFullPath($oldProcess.ExecutablePath), [System.IO.Path]::GetFullPath($qemu), [System.StringComparison]::OrdinalIgnoreCase)
            $oldCommandMatches = $oldProcess.CommandLine.Contains('file=./data.qcow2,if=virtio,format=qcow2')
            $oldQmpListener = Get-NetTCPConnection -State Listen -LocalPort 18788 -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $oldId
            if ($oldPathMatches -and $oldCommandMatches -and $oldQmpListener) {
                Write-Output "SwitchFleet is already running (PID $oldIdText); checking its web service."
                for ($attempt = 0; $attempt -lt 48; $attempt++) {
                    if (-not (Get-Process -Id $oldId -ErrorAction SilentlyContinue)) { throw 'The recorded SwitchFleet QEMU process exited during startup.' }
                    $probe = & curl.exe --noproxy '*' --connect-timeout 3 -sS -o NUL -w '%{http_code}' $url 2>$null
                    if ($LASTEXITCODE -eq 0 -and $probe -eq '200') {
                        Start-Process $url
                        Write-Output "SwitchFleet is ready at $url"
                        return
                    }
                    Start-Sleep -Seconds 5
                }
                throw "The running SwitchFleet VM did not return HTTP 200 within 4 minutes."
            }
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}
if (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object LocalPort -in 18787,18788) {
    throw 'A required loopback port (18787 or 18788) is already in use.'
}

if (-not (Test-Path -LiteralPath $dataDisk)) {
    Push-Location $runtime
    try {
        & $qemuImg create -f qcow2 -F qcow2 -b './switchfleet-v1.qcow2' './data.qcow2' '24G'
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the writable data overlay.' }
    } finally { Pop-Location }
}

$qemuArguments = @(
    '-machine', 'q35,accel=tcg,usb=off',
    '-cpu', 'max',
    '-smp', '2',
    '-m', '3072',
    # Pass ASCII paths relative to the runtime working directory. QEMU's
    # Windows build may fail to open drive paths containing non-ASCII chars.
    '-L', 'qemu\share',
    '-drive', 'file=./data.qcow2,if=virtio,format=qcow2',
    '-netdev', 'user,id=net0,restrict=off,hostfwd=tcp:127.0.0.1:18787-:8787',
    '-device', 'virtio-net-pci,netdev=net0',
    '-display', 'none',
    '-monitor', 'none',
    '-qmp', 'tcp:127.0.0.1:18788,server=on,wait=off',
    '-serial', 'file:./switchfleet-qemu.serial.log',
    '-no-reboot'
)
$argumentLine = ($qemuArguments | ForEach-Object { ConvertTo-WindowsCommandLineArgument ([string]$_) }) -join ' '
$proc = Start-Process -FilePath $qemu -ArgumentList $argumentLine -WorkingDirectory $runtime -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ascii
Write-Output "SwitchFleet Linux VM started hidden (PID $($proc.Id), QEMU TCG). Waiting for $url"

$ready = $false
for ($attempt = 0; $attempt -lt 48; $attempt++) {
    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { throw "QEMU exited before web startup. See $stderrLog and $serialLog" }
    $probe = & curl.exe --noproxy '*' --connect-timeout 3 -sS -o NUL -w '%{http_code}' $url 2>$null
    if ($LASTEXITCODE -eq 0 -and $probe -eq '200') { $ready = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ready) { throw "Web service did not return HTTP 200 within 4 minutes. See $stderrLog and $serialLog" }
Start-Process $url
Write-Output "SwitchFleet is ready at $url"
