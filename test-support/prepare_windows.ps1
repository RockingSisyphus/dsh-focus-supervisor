param([string]$Root='C:\DafeiyuTest')
$ErrorActionPreference='Stop'
$spec=Get-Content "$PSScriptRoot\runtime.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$node="$Root\node-v$($spec.node)-win-x64"
if(!(Test-Path "$node\node.exe")) {
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 "https://nodejs.org/dist/v$($spec.node)/node-v$($spec.node)-win-x64.zip" -OutFile "$Root\node.zip"
  Expand-Archive "$Root\node.zip" $Root -Force
}
# Deep evidence and test artifact paths require the standard Win32 long-path opt-in.
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1
# Unattended runs must not stall on the lock screen: turn off the
# "require sign-in on wakeup" setting and disable the lock screen itself.
powercfg /setacvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 | Out-Null
powercfg /setdcvalueindex SCHEME_CURRENT SUB_NONE CONSOLELOCK 0 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
New-Item 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Force | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' -Name NoLockScreen -Value 1
Write-Output 'Lock screen disabled for unattended runs'
# A stock machine has python.exe on PATH (or registered under PythonCore); this guest
# ships a portable Python, so register it the same way backend installers expect.
$portablePython=Get-ChildItem "$Root\Python*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if($portablePython){
  $directory=Split-Path $portablePython.FullName -Parent
  $machine=[Environment]::GetEnvironmentVariable('Path','Machine')
  if($machine -notlike "*$directory*"){
    [Environment]::SetEnvironmentVariable('Path',$machine.TrimEnd(';')+';'+$directory,'Machine')
    Write-Output "Registered $directory on the machine PATH"
  }
  # Also register PythonCore like the official installer, so a process that inherited an
  # older environment (services cache it) can still find an interpreter.
  $version=(& $portablePython.FullName -c "import sys;print('%d.%d'%sys.version_info[:2])").Trim()
  $key="HKLM:\SOFTWARE\Python\PythonCore\$version\InstallPath"
  if(!(Test-Path $key)){New-Item -Path $key -Force | Out-Null}
  Set-Item -Path $key -Value $directory
  Write-Output "Registered PythonCore $version -> $directory"
}
$env:PATH="$node;"+$env:PATH
if(!(Test-Path "$Root\venv\Scripts\python.exe")){throw 'Prepare Python venv under Root\venv first'}
$packages=$spec.python -join ' '
cmd /c "`"$Root\venv\Scripts\python.exe`" -m pip install $packages > `"$Root\pip-dsh.log`" 2>&1"
if($LASTEXITCODE -ne 0){throw 'Python dependencies failed; see pip-dsh.log'}
New-Item "$Root\dsh-runtime" -ItemType Directory -Force | Out-Null
Push-Location "$Root\dsh-runtime"
try {
 $packages=($spec.npm.PSObject.Properties | ForEach-Object {"$($_.Name)@$($_.Value)"}) -join ' '
 cmd /c "npm install --no-audit --no-fund $packages > `"$Root\npm-dsh.log`" 2>&1"
 if($LASTEXITCODE -ne 0){throw 'DSH dependencies failed; see npm-dsh.log'}
} finally {Pop-Location}
# dsh plugin add is a pnpm forwarder, so the guest needs pnpm on PATH.
if(!(Get-Command pnpm -ErrorAction SilentlyContinue)) {
  cmd /c "npm install -g --no-audit --no-fund pnpm > `"$Root\npm-pnpm.log`" 2>&1"
  if($LASTEXITCODE -ne 0){throw 'pnpm installation failed; see npm-pnpm.log'}
}
if(!(Test-Path "$Root\project\dsh-plugin\node_modules")) {
 cmd /c "mklink /J `"$Root\project\dsh-plugin\node_modules`" `"$Root\dsh-runtime\node_modules`""
 if($LASTEXITCODE -ne 0){throw 'Node modules junction failed'}
}
Write-Output 'Windows DSH test runtime prepared; browser uses installed Edge.'
