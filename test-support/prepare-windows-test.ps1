# Prepare on-demand capture in the existing signed-in desktop; never auto-start capture.
param(
    [string]$Root = 'C:\DafeiyuTest',
    [string]$Account = (Get-CimInstance Win32_ComputerSystem).UserName
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not $Account) { throw 'Log in to the Windows desktop first.' }
$python = Join-Path $Root 'venv\Scripts\pythonw.exe'
$project = Join-Path $Root 'project'
$script = Join-Path $project 'dshmonitor-test-pack\runtime\windows_capture.py'
if (!(Test-Path $python) -or !(Test-Path $script)) { throw 'Python environment or capture script is missing.' }
& icacls.exe $Root /grant "${Account}:(OI)(CI)M" /T /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Unable to grant the desktop account access to the test directory.' }
$principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
foreach ($mode in @('ready','capture')) {
    $out = Join-Path $Root "results\$mode"
    New-Item -ItemType Directory -Force $out | Out-Null
    $arguments = '"' + $script + '" --output "' + $out + '"'
    if ($mode -eq 'ready') { $arguments += ' --ready-only' }
    $action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $project
    Register-ScheduledTask -TaskName "Dafeiyu-Test-$mode" -Action $action -Principal $principal -Settings $settings -Force | Out-Null
}
# This checks session and imports only; it does not enumerate or capture applications.
Start-ScheduledTask -TaskName 'Dafeiyu-Test-ready'
Write-Output 'Registered on-demand tasks. Capture task has NOT been started.'
