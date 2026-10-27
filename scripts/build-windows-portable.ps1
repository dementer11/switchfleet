[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeDirectory,

    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\dist\SwitchFleet-Windows'),

    [string]$ZipPath
)

$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathWithin([string]$Root, [string]$Candidate) {
    $rootPrefix = $Root.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    return $Candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-OutputPath([string]$Root, [string]$RelativePath) {
    $candidate = Get-FullPath (Join-Path $Root $RelativePath)
    if (-not (Test-PathWithin $Root $candidate)) {
        throw "Refusing destination outside output directory: $candidate"
    }
    return $candidate
}

function Assert-TrustedQemuTree([string]$Root) {
    $entries = @((Get-Item -LiteralPath $Root -Force)) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse -ErrorAction Stop)
    foreach ($entry in $entries) {
        $attributes = [System.IO.File]::GetAttributes($entry.FullName)
        if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "QEMU source contains a reparse point; refusing recursive copy: $($entry.FullName)"
        }

        $name = $entry.Name
        $extension = [System.IO.Path]::GetExtension($name)
        $privateName = $name -match '^(known_hosts|authorized_keys|id_(rsa|dsa|ecdsa|ed25519))$' -or
            $name -match '(?i)user[-_]?attachments?'
        $privateExtension = $extension -match '(?i)^\.(key|pem|ppk|pub|log|pid|qcow2|xlsx|xls|xlsm|csv)$' -or
            $name -like '*.vhd*'
        if ($privateName -or $privateExtension) {
            throw "QEMU source contains a private or user-data file; refusing recursive copy: $($entry.FullName)"
        }
    }
}

if (-not (Test-Path -LiteralPath $RuntimeDirectory -PathType Container)) {
    throw "Runtime directory does not exist: $RuntimeDirectory"
}
$runtimeRoot = (Resolve-Path -LiteralPath $RuntimeDirectory).Path
$imageSource = Join-Path $runtimeRoot 'switchfleet-v1.qcow2'
$qemuSource = Join-Path $runtimeRoot 'qemu'
$manifestSource = Join-Path $runtimeRoot 'runtime-manifest.json'
foreach ($required in @(
    @{ Path = $imageSource; Type = 'Leaf' },
    @{ Path = $qemuSource; Type = 'Container' },
    @{ Path = $manifestSource; Type = 'Leaf' },
    @{ Path = (Join-Path $qemuSource 'qemu-system-x86_64.exe'); Type = 'Leaf' },
    @{ Path = (Join-Path $qemuSource 'qemu-img.exe'); Type = 'Leaf' },
    @{ Path = (Join-Path $qemuSource 'share'); Type = 'Container' }
)) {
    $valid = if ($required.Type -eq 'Container') {
        Test-Path -LiteralPath $required.Path -PathType Container
    } else {
        Test-Path -LiteralPath $required.Path -PathType Leaf
    }
    if (-not $valid) { throw "Required runtime component is missing: $($required.Path)" }
}
Assert-TrustedQemuTree $qemuSource

$templateRoot = Join-Path $PSScriptRoot '..\deployment\windows'
$staticFiles = @(
    'Start-SwitchFleet.ps1',
    'Stop-SwitchFleet.ps1',
    'Start-SwitchFleet.cmd',
    'Run-SwitchFleet.cmd',
    'Stop-SwitchFleet.cmd',
    'README.txt'
)
foreach ($name in $staticFiles) {
    $template = Join-Path $templateRoot $name
    if (-not (Test-Path -LiteralPath $template -PathType Leaf)) {
        throw "Windows package template is missing: $template"
    }
}

$outputFull = Get-FullPath $OutputDirectory
if ($outputFull.Equals($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase) -or (Test-PathWithin $runtimeRoot $outputFull)) {
    throw 'Output directory must not be inside the runtime directory.'
}
if (Test-Path -LiteralPath $outputFull) {
    if (-not (Test-Path -LiteralPath $outputFull -PathType Container)) {
        throw "Output path exists and is not a directory: $outputFull"
    }
    $existing = @(Get-ChildItem -LiteralPath $outputFull -Force)
    if ($existing.Count -gt 0) {
        if (Test-Path -LiteralPath (Join-Path $outputFull 'data.qcow2')) {
            throw "Output directory contains writable data.qcow2; refusing to overwrite any existing contents: $outputFull"
        }
        throw "Output directory must be new or empty; refusing to overwrite existing contents: $outputFull"
    }
} else {
    New-Item -ItemType Directory -Path $outputFull -Force | Out-Null
}
$outputRoot = (Resolve-Path -LiteralPath $outputFull).Path
if ($outputRoot.Equals($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase) -or (Test-PathWithin $runtimeRoot $outputRoot)) {
    throw 'Output directory must not be inside the runtime directory.'
}

$copyMap = @(
    @{ Source = $imageSource; Relative = 'switchfleet-v1.qcow2'; Recurse = $false },
    @{ Source = $manifestSource; Relative = 'runtime-manifest.json'; Recurse = $false },
    @{ Source = $qemuSource; Relative = 'qemu'; Recurse = $true }
)
foreach ($name in $staticFiles) {
    $copyMap += @{ Source = (Join-Path $templateRoot $name); Relative = $name; Recurse = $false }
}
foreach ($item in $copyMap) {
    $destination = Assert-OutputPath $outputRoot $item.Relative
    if ($item.Recurse) {
        Copy-Item -LiteralPath $item.Source -Destination $destination -Recurse
    } else {
        Copy-Item -LiteralPath $item.Source -Destination $destination
    }
}

if ($ZipPath) {
    $sevenZip = Get-Command '7z.exe' -ErrorAction SilentlyContinue
    if (-not $sevenZip) { $sevenZip = Get-Command '7z' -ErrorAction SilentlyContinue }
    if (-not $sevenZip) { throw '7-Zip was not found. Omit -ZipPath or install/use an available 7z.exe.' }
    $zipFull = Get-FullPath $ZipPath
    if (Test-PathWithin $outputRoot $zipFull) {
        throw 'ZipPath must be outside OutputDirectory to avoid including the archive in itself.'
    }
    if (Test-Path -LiteralPath $zipFull) { throw "ZIP destination already exists; refusing to overwrite it: $zipFull" }
    $zipParent = Split-Path -Parent $zipFull
    if (-not (Test-Path -LiteralPath $zipParent -PathType Container)) {
        New-Item -ItemType Directory -Path $zipParent -Force | Out-Null
    }
    & $sevenZip.Source 'a' '-tzip' '-mx=9' $zipFull (Join-Path $outputRoot '*')
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE" }
}

Write-Output "SwitchFleet portable files assembled at: $outputRoot"
