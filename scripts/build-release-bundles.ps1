param(
    [string]$Version = "0.2.0",
    [string]$OutDir = "dist",
    [string]$PythonExe = "python",
    [string]$PythonEmbedVersion = "3.12.10",
    [switch]$SkipPortable
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutPath = Join-Path $RepoRoot $OutDir
$BuildRoot = Join-Path $OutPath "release-build"
$WheelRoot = Join-Path $BuildRoot "wheelhouse"
$SupportedPythonVersions = @("310", "311", "312", "313")
$RuntimeRequirements = @(
    "alembic>=1.13",
    "celery>=5.4",
    "cryptography>=42",
    "fastapi>=0.115",
    "jinja2>=3.1",
    "netmiko>=4.4",
    "openpyxl>=3.1",
    "paramiko>=3.4",
    "psycopg[binary]>=3.2",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "redis>=5",
    "scrapli>=2024.7.30",
    "sqlalchemy>=2.0",
    "structlog>=24.4",
    "uvicorn[standard]>=0.30"
)

function Invoke-Step($Name, [scriptblock]$Body) {
    Write-Host "==> $Name"
    & $Body
}

function New-CleanDir($Path) {
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path | Out-Null
}

function Add-FindLinksArgs($BasePath) {
    $args = @()
    Get-ChildItem -LiteralPath $BasePath -Directory -Recurse | ForEach-Object {
        $args += @("--find-links", $_.FullName)
    }
    $args += @("--find-links", $BasePath)
    return $args
}

function Write-Sha256($Path) {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$Path.sha256" -Value "sha256:$hash  $(Split-Path -Leaf $Path)" -Encoding ascii
}

function New-TarGz($SourceDir, $Destination) {
    $code = @'
import os
import sys
import tarfile

src = os.path.abspath(sys.argv[1])
dst = os.path.abspath(sys.argv[2])
base = os.path.basename(src.rstrip(os.sep))

with tarfile.open(dst, 'w:gz', format=tarfile.PAX_FORMAT) as tar:
    root_info = tar.gettarinfo(src, base)
    root_info.mode = 0o755
    tar.addfile(root_info)
    for root, dirs, files in os.walk(src):
        for name in dirs + files:
            path = os.path.join(root, name)
            arcname = os.path.join(base, os.path.relpath(path, src)).replace(os.sep, '/')
            info = tar.gettarinfo(path, arcname)
            if os.path.isdir(path):
                info.mode = 0o755
                tar.addfile(info)
                continue
            info.mode = 0o755 if (name.endswith('.sh') or name == 'switchfleet') else 0o644
            with open(path, 'rb') as fh:
                tar.addfile(info, fh)
'@
    & $PythonExe -c $code $SourceDir $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "tar.gz creation failed for $SourceDir"
    }
}

function Copy-ProjectFiles($Target) {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -LiteralPath (Join-Path $RepoRoot "README.md") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot "pyproject.toml") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.example") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot "Dockerfile") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot "docker-compose.yml") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot "alembic.ini") -Destination $Target
    Copy-Item -LiteralPath (Join-Path $RepoRoot "app") -Destination $Target -Recurse
    Copy-Item -LiteralPath (Join-Path $RepoRoot "src") -Destination $Target -Recurse
    Copy-Item -LiteralPath (Join-Path $RepoRoot "docs") -Destination $Target -Recurse
    Copy-Item -LiteralPath (Join-Path $RepoRoot "alembic") -Destination $Target -Recurse
}

function Download-Wheelhouse($PlatformName, $PlatformTag, $PythonVersion) {
    $dest = Join-Path $WheelRoot "$PlatformName\cp$PythonVersion"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & $PythonExe -m pip download `
        --dest $dest `
        --only-binary=:all: `
        --platform $PlatformTag `
        --implementation cp `
        --python-version $PythonVersion `
        $RuntimeRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "pip download failed for $PlatformName cp$PythonVersion"
    }
}

Invoke-Step "Clean output" {
    New-CleanDir $BuildRoot
    New-Item -ItemType Directory -Force -Path $OutPath | Out-Null
}

Invoke-Step "Build project wheel" {
    $projectWheelDir = Join-Path $WheelRoot "project"
    New-Item -ItemType Directory -Force -Path $projectWheelDir | Out-Null
    & $PythonExe -m pip wheel --no-deps --wheel-dir $projectWheelDir $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Project wheel build failed"
    }
}

Invoke-Step "Download offline wheelhouses" {
    foreach ($py in $SupportedPythonVersions) {
        Download-Wheelhouse "windows-amd64" "win_amd64" $py
        Download-Wheelhouse "linux-x86_64" "manylinux2014_x86_64" $py
    }
}

Invoke-Step "Create Windows offline installer" {
    $root = Join-Path $BuildRoot "switchfleet-windows-offline-$Version"
    New-CleanDir $root
    Copy-ProjectFiles (Join-Path $root "source")
    Copy-Item -LiteralPath (Join-Path $WheelRoot "project") -Destination (Join-Path $root "wheelhouse") -Recurse
    Copy-Item -LiteralPath (Join-Path $WheelRoot "windows-amd64") -Destination (Join-Path $root "wheelhouse") -Recurse
    Set-Content -LiteralPath (Join-Path $root "install.ps1") -Encoding utf8 -Value @'
param(
    [string]$InstallDir = "$PSScriptRoot\app",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$venv = Join-Path $InstallDir ".venv"
& $Python -c "import platform, sys; v=sys.version_info[:2]; m=platform.machine().lower(); raise SystemExit(0 if ((3, 10) <= v <= (3, 13) and m in {'amd64','x86_64'}) else 'Python 3.10-3.13 x64 is required by bundled offline wheels')"
if ($LASTEXITCODE -ne 0) { throw "Unsupported Python runtime" }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
& $Python -m venv $venv
$venvPython = Join-Path $venv "Scripts\python.exe"
$findLinks = @()
$findLinks += @("--find-links", (Join-Path $PSScriptRoot "wheelhouse"))
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "wheelhouse") -Directory -Recurse | ForEach-Object {
    $findLinks += @("--find-links", $_.FullName)
}
& $venvPython -m pip install --no-index @findLinks "netops-orchestrator"
if ($LASTEXITCODE -ne 0) { throw "Offline install failed" }
Set-Content -LiteralPath (Join-Path $PSScriptRoot "switchfleet.cmd") -Encoding ascii -Value "@echo off`r`n`"$venvPython`" -m netops_orchestrator.cli %*`r`n"
Set-Content -LiteralPath (Join-Path $PSScriptRoot "switchfleet-api.cmd") -Encoding ascii -Value "@echo off`r`n`"$venvPython`" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 %*`r`n"
Write-Host "Installed. Run: .\switchfleet.cmd --help"
'@
    Set-Content -LiteralPath (Join-Path $root "install.cmd") -Encoding ascii -Value '@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
'
    Set-Content -LiteralPath (Join-Path $root "README-WINDOWS.txt") -Encoding utf8 -Value "Offline Windows install:`r`n1. Extract archive.`r`n2. Run install.cmd.`r`n3. Run switchfleet.cmd --help.`r`n"
    Compress-Archive -Path (Join-Path $root "*") -DestinationPath (Join-Path $OutPath "switchfleet-windows-offline-$Version.zip") -Force
    Write-Sha256 (Join-Path $OutPath "switchfleet-windows-offline-$Version.zip")
}

Invoke-Step "Create Linux offline installer" {
    $root = Join-Path $BuildRoot "switchfleet-linux-offline-$Version"
    New-CleanDir $root
    Copy-ProjectFiles (Join-Path $root "source")
    Copy-Item -LiteralPath (Join-Path $WheelRoot "project") -Destination (Join-Path $root "wheelhouse") -Recurse
    Copy-Item -LiteralPath (Join-Path $WheelRoot "linux-x86_64") -Destination (Join-Path $root "wheelhouse") -Recurse
    Set-Content -LiteralPath (Join-Path $root "install.sh") -Encoding ascii -Value @'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_DIR="${INSTALL_DIR:-"$SCRIPT_DIR/app"}"

"$PYTHON_BIN" - <<'PY'
import sys
if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
    raise SystemExit("Python 3.10-3.13 is required by bundled offline wheels")
PY

mkdir -p "$INSTALL_DIR"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
VENV_PY="$INSTALL_DIR/.venv/bin/python"
FIND_LINKS=()
FIND_LINKS+=(--find-links "$SCRIPT_DIR/wheelhouse")
while IFS= read -r -d '' dir; do
  FIND_LINKS+=(--find-links "$dir")
done < <(find "$SCRIPT_DIR/wheelhouse" -type d -print0)
"$VENV_PY" -m pip install --no-index "${FIND_LINKS[@]}" "netops-orchestrator"
cat > "$SCRIPT_DIR/switchfleet" <<EOF
#!/usr/bin/env bash
exec "$VENV_PY" -m netops_orchestrator.cli "\$@"
EOF
chmod +x "$SCRIPT_DIR/switchfleet"
cat > "$SCRIPT_DIR/switchfleet-api" <<EOF
#!/usr/bin/env bash
exec "$VENV_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 "\$@"
EOF
chmod +x "$SCRIPT_DIR/switchfleet-api"
echo "Installed. Run: ./switchfleet --help"
'@
    Set-Content -LiteralPath (Join-Path $root "README-LINUX.txt") -Encoding utf8 -Value "Offline Linux install:`n1. tar -xzf archive.`n2. cd extracted directory.`n3. ./install.sh.`n4. ./switchfleet --help.`n"
    New-TarGz $root (Join-Path $OutPath "switchfleet-linux-offline-$Version.tar.gz")
    Write-Sha256 (Join-Path $OutPath "switchfleet-linux-offline-$Version.tar.gz")
}

Invoke-Step "Create RED OS 7.3.6 offline installer" {
    $root = Join-Path $BuildRoot "switchfleet-redos-7.3.6-offline-$Version"
    New-CleanDir $root
    Copy-ProjectFiles (Join-Path $root "source")
    Copy-Item -LiteralPath (Join-Path $WheelRoot "project") -Destination (Join-Path $root "wheelhouse") -Recurse
    Copy-Item -LiteralPath (Join-Path $WheelRoot "linux-x86_64") -Destination (Join-Path $root "wheelhouse") -Recurse
    Set-Content -LiteralPath (Join-Path $root "install-redos.sh") -Encoding ascii -Value @'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_DIR="${INSTALL_DIR:-"$SCRIPT_DIR/app"}"

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  echo "Detected OS: ${PRETTY_NAME:-unknown}"
fi

"$PYTHON_BIN" - <<'PY'
import platform, sys
if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
    raise SystemExit("Python 3.10-3.13 is required by bundled offline wheels. Install a supported Python from your RED OS media/repo first.")
machine = platform.machine().lower()
if machine not in {"x86_64", "amd64"}:
    raise SystemExit(f"x86_64 is required for bundled wheels, got {machine}")
PY

mkdir -p "$INSTALL_DIR"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
VENV_PY="$INSTALL_DIR/.venv/bin/python"
FIND_LINKS=()
FIND_LINKS+=(--find-links "$SCRIPT_DIR/wheelhouse")
while IFS= read -r -d '' dir; do
  FIND_LINKS+=(--find-links "$dir")
done < <(find "$SCRIPT_DIR/wheelhouse" -type d -print0)
"$VENV_PY" -m pip install --no-index "${FIND_LINKS[@]}" "netops-orchestrator"
cat > "$SCRIPT_DIR/switchfleet" <<EOF
#!/usr/bin/env bash
exec "$VENV_PY" -m netops_orchestrator.cli "\$@"
EOF
chmod +x "$SCRIPT_DIR/switchfleet"
cat > "$SCRIPT_DIR/switchfleet-api" <<EOF
#!/usr/bin/env bash
exec "$VENV_PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 "\$@"
EOF
chmod +x "$SCRIPT_DIR/switchfleet-api"
echo "Installed. Run: ./switchfleet --help"
'@
    Set-Content -LiteralPath (Join-Path $root "install.sh") -Encoding ascii -Value @'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/install-redos.sh" "$@"
'@
    Set-Content -LiteralPath (Join-Path $root "README-REDOS-7.3.6.txt") -Encoding utf8 -Value "Offline RED OS 7.3.6 install:`n1. tar -xzf archive.`n2. cd extracted directory.`n3. ./install-redos.sh.`n4. ./switchfleet --help.`n"
    New-TarGz $root (Join-Path $OutPath "switchfleet-redos-7.3.6-offline-$Version.tar.gz")
    Write-Sha256 (Join-Path $OutPath "switchfleet-redos-7.3.6-offline-$Version.tar.gz")
}

if (-not $SkipPortable) {
    Invoke-Step "Create Windows portable bundle" {
        $root = Join-Path $BuildRoot "switchfleet-windows-portable-$Version"
        New-CleanDir $root
        $pythonDir = Join-Path $root "python"
        $appDir = Join-Path $root "app"
        $embedZip = Join-Path $BuildRoot "python-$PythonEmbedVersion-embed-amd64.zip"
        $embedUrl = "https://www.python.org/ftp/python/$PythonEmbedVersion/python-$PythonEmbedVersion-embed-amd64.zip"
        Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip
        Expand-Archive -LiteralPath $embedZip -DestinationPath $pythonDir -Force
        New-Item -ItemType Directory -Force -Path (Join-Path $pythonDir "Lib\site-packages") | Out-Null
        Copy-ProjectFiles $appDir
        & $PythonExe -m pip install --target (Join-Path $pythonDir "Lib\site-packages") $RuntimeRequirements
        if ($LASTEXITCODE -ne 0) {
            throw "Portable dependency install failed"
        }
        $pth = Get-ChildItem -LiteralPath $pythonDir -Filter "python*._pth" | Select-Object -First 1
        if ($pth) {
            Set-Content -LiteralPath $pth.FullName -Encoding ascii -Value @"
python312.zip
.
Lib\site-packages
..\app
..\app\src
import site
"@
        }
        Set-Content -LiteralPath (Join-Path $root "switchfleet.cmd") -Encoding ascii -Value '@echo off
set "ROOT=%~dp0"
"%ROOT%python\python.exe" -m netops_orchestrator.cli %*
'
        Set-Content -LiteralPath (Join-Path $root "switchfleet-api.cmd") -Encoding ascii -Value '@echo off
set "ROOT=%~dp0"
"%ROOT%python\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 %*
'
        Set-Content -LiteralPath (Join-Path $root "README-PORTABLE.txt") -Encoding utf8 -Value "Windows portable:`r`n1. Extract archive anywhere.`r`n2. Run switchfleet.cmd --help.`r`nNo Python installation is required.`r`n"
        Compress-Archive -Path (Join-Path $root "*") -DestinationPath (Join-Path $OutPath "switchfleet-windows-portable-$Version.zip") -Force
        Write-Sha256 (Join-Path $OutPath "switchfleet-windows-portable-$Version.zip")
    }
}

Invoke-Step "List artifacts" {
    Get-ChildItem -LiteralPath $OutPath -File | Where-Object { $_.Name -like "switchfleet-*" } | Sort-Object Name | Select-Object Name, Length
}
