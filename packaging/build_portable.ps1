#requires -Version 5.1
<#
.SYNOPSIS
  Assemble the portable Windows bundle of LoRA Dataset Studio.

.DESCRIPTION
  Produces packaging/dist/LoRA-Dataset-Studio-win64.zip: a self-contained folder the
  end user extracts and runs by double-clicking "LoRA Dataset Studio.exe" — no Python
  install, no terminal. The heavy externals (ComfyUI, ai-toolkit, Ollama, ML extras)
  stay OUT of the bundle: the in-app Setup wizard installs them. This is why we ship a
  real standalone CPython (which HAS pip) instead of a single frozen exe — the wizard's
  `pip install -r backend/requirements-ml.txt` runs against the bundled interpreter.

  Bundle layout (mirrors the repo so backend/config.py resolves REPO_ROOT/FRONTEND_DIST
  unchanged):
      LoRA Dataset Studio.exe   python\   backend\   frontend\dist\   icon.ico   README.md

.NOTES
  Prereqs on the BUILD machine: PowerShell 5.1+, a host `python` (3.9-3.12) on PATH
  (only used to run PyInstaller for the launcher), tar.exe (built into Windows 10+),
  and internet access. The end user needs none of this.

  Distribute the resulting .zip as a GitHub Release asset. Unsigned: SmartScreen will
  warn "unknown publisher" (More info -> Run anyway). Code-signing is a later add-on.
#>
[CmdletBinding()]
param(
  [string]$PyAsset = 'cpython-3.11.15+20260718-x86_64-pc-windows-msvc-install_only.tar.gz',
  [ValidatePattern('^[0-9a-f]{64}$')]
  [string]$PySha256 = 'c3d782be3733f779d585633da374ff1bd92400d4d74c0c3922aee1526446096b',
  [string]$OutName = 'LoRA-Dataset-Studio'
)
$ErrorActionPreference = 'Stop'
$Here  = $PSScriptRoot
$Root  = Split-Path -Parent $Here
$Build = Join-Path $Here 'build'
$Stage = Join-Path $Here "dist\$OutName"
$Zip   = Join-Path $Here "dist\$OutName-win64.zip"
$PythonRelease = '20260718'

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

Step 'Clean workspace'
Remove-Item -Recurse -Force $Build, $Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Build, $Stage, (Split-Path $Zip) | Out-Null

# 1) Fetch one immutable, reviewed CPython asset and verify its publisher digest.
#    Updating Python is an intentional code review change to all three constants.
Step "Downloading pinned python-build-standalone $PyAsset"
$tar = Join-Path $Build $PyAsset
$encodedAsset = $PyAsset.Replace('+', '%2B')
$pythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PythonRelease/$encodedAsset"
Invoke-WebRequest -UseBasicParsing -Uri $pythonUrl -OutFile $tar
$actualPythonHash = (Get-FileHash -Algorithm SHA256 $tar).Hash.ToLowerInvariant()
if ($actualPythonHash -ne $PySha256.ToLowerInvariant()) {
  throw "Standalone Python checksum mismatch: expected $PySha256, got $actualPythonHash."
}

Step 'Extracting Python into the bundle'
tar -xzf $tar -C $Build                       # -> $Build\python\...
$Py = Join-Path $Stage 'python'
Move-Item (Join-Path $Build 'python') $Py
$PyExe = Join-Path $Py 'python.exe'

# 2) Runtime deps (core requirements minus pytest) into the SHIPPED interpreter.
Step 'Installing runtime deps into the bundle'
& $PyExe -m pip --version *> $null
if ($LASTEXITCODE -ne 0) { & $PyExe -m ensurepip --default-pip }
$reqRun = Join-Path $Build 'requirements-runtime.txt'
Get-Content (Join-Path $Root 'backend\requirements.txt') |
  Where-Object { $_ -notmatch '^\s*pytest' } | Set-Content $reqRun
& $PyExe -m pip install --no-warn-script-location --disable-pip-version-check -r $reqRun
if ($LASTEXITCODE -ne 0) { throw 'pip install of runtime deps failed.' }

# 3) App files — mirror the repo so REPO_ROOT/FRONTEND_DIST resolve unchanged.
Step 'Staging app files'
robocopy (Join-Path $Root 'backend') (Join-Path $Stage 'backend') /E `
  /XD __pycache__ tests .venv /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy backend failed ($LASTEXITCODE)." }
$global:LASTEXITCODE = 0
New-Item -ItemType Directory -Force (Join-Path $Stage 'frontend') | Out-Null
Copy-Item -Recurse -Force (Join-Path $Root 'frontend\dist') (Join-Path $Stage 'frontend\dist')
Copy-Item -Force (Join-Path $Here 'icon.ico') $Stage
Copy-Item -Force (Join-Path $Root 'README.md') $Stage -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $Root 'LICENSE')   $Stage -ErrorAction SilentlyContinue

# 4) Launcher exe (host python + PyInstaller; tkinter is bundled automatically).
#    PyInstaller needs CPython 3.9-3.12 — bare `python` may resolve to a newer one
#    (the exact trap start.bat dodges for the ML extras), so resolve a compatible
#    host interpreter through the py launcher first, newest supported first.
Step 'Building the launcher exe (PyInstaller)'
# PS 5.1 gotcha: with $ErrorActionPreference='Stop', a NATIVE command writing to
# stderr WHILE redirected (2>$null / *>$null) raises a terminating
# NativeCommandError — pip's "WARNING: Package(s) not found" killed the build.
# Relax EAP around the native probes and trust $LASTEXITCODE instead.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$HostPy = $null
foreach ($v in '3.12', '3.11', '3.10', '3.9') {
  $exe = & py "-$v" -c 'import sys; print(sys.executable)' 2>$null
  if ($LASTEXITCODE -eq 0 -and $exe) { $HostPy = "$exe".Trim(); break }
}
if (-not $HostPy) { $HostPy = 'python' }   # last resort — may fail on 3.13+
Write-Host "    host python for PyInstaller: $HostPy"
& $HostPy -m pip install --disable-pip-version-check -r (Join-Path $Here 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { $ErrorActionPreference = $prevEAP; throw 'pinned PyInstaller install failed.' }
$ErrorActionPreference = $prevEAP
& $HostPy -m PyInstaller --noconfirm --onefile --noconsole `
  --name 'LoRA Dataset Studio' --icon (Join-Path $Here 'icon.ico') `
  --distpath (Join-Path $Build 'launcher') --workpath (Join-Path $Build 'pyi') `
  --specpath $Build (Join-Path $Here 'launcher.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -Force (Join-Path $Build 'launcher\LoRA Dataset Studio.exe') $Stage

# 5) Zip the folder (extraction yields the LoRA-Dataset-Studio\ folder).
Step 'Zipping the bundle'
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path $Stage -DestinationPath $Zip
$mb = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Step "Done -> $Zip ($mb MB)"
Write-Host '    Test it: extract the zip and double-click "LoRA Dataset Studio.exe".'
