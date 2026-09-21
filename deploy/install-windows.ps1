param([string]$Root='',[string]$Python='',[string]$TaskName='Dafeiyu-Supervisor',[string]$DshTask='Dafeiyu-DSH')
$ErrorActionPreference='Stop'
# 绝不静默装到盘符根目录：没有 ProgramData 就要求显式指定安装目录。
if(!$Root){
  if(!$env:ProgramData){throw '环境变量 ProgramData 缺失：请用 -Root <安装目录> 明确指定安装位置。'}
  $Root=Join-Path $env:ProgramData 'Dafeiyu'
}
# 后台把安装输出直接显示在面板里；按 UTF-8 输出，避免中文报错变成乱码。
try { [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new() } catch {}
# python.exe is frequently installed without being on PATH (and the plugin spawns this
# script with the system PATH), so resolve a real interpreter ourselves and report
# clearly when there is none, instead of failing later with "not recognized".
function Test-Python([string]$Candidate){
  if(!$Candidate -or !(Test-Path $Candidate)){return $false}
  & $Candidate -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>$null
  return ($LASTEXITCODE -eq 0)
}
function Resolve-Python([string]$Requested){
  $names=@(); if($Requested){$names+=$Requested}
  $names+='python.exe','python3.exe','py.exe'
  $candidates=@()
  foreach($name in $names){
    $command=Get-Command $name -ErrorAction SilentlyContinue
    if($command){$candidates+=$command.Source}
  }
  foreach($key in @('HKLM:\SOFTWARE\Python\PythonCore','HKCU:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore')){
    if(Test-Path $key){
      foreach($version in @(Get-ChildItem $key -ErrorAction SilentlyContinue)){
        $install=Get-Item -Path ($key+'\'+$version.PSChildName+'\InstallPath') -ErrorAction SilentlyContinue
        if($install){ $directory=$install.GetValue(''); if($directory){$candidates+=Join-Path $directory 'python.exe'} }
      }
    }
  }
  $patterns=@()
  if($env:LOCALAPPDATA){$patterns+="$env:LOCALAPPDATA\Programs\Python\Python*\python.exe"}
  if($env:ProgramFiles){$patterns+="$env:ProgramFiles\Python*\python.exe"}
  if(${env:ProgramFiles(x86)}){$patterns+="${env:ProgramFiles(x86)}\Python*\python.exe"}
  $patterns+='C:\Python*\python.exe'
  foreach($pattern in $patterns){
    $candidates+=@(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
  }
  # A Microsoft Store app-execution alias also answers to python.exe; only a candidate
  # that really runs Python 3 counts.
  foreach($candidate in $candidates){ if(Test-Python $candidate){ return $candidate } }
  return $null
}
$pythonPath=Resolve-Python $Python
if(!$pythonPath){throw '未找到可用的 Python 3：请先安装 Python 3（可勾选 Add python.exe to PATH），或用 -Python <python.exe 完整路径> 指定后重试。'}
$identity=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if(!$identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $arguments="-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Root `"$Root`" -Python `"$pythonPath`" -TaskName `"$TaskName`" -DshTask `"$DshTask`""
  $elevated=Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
  exit $elevated.ExitCode
}
# win32ui (native window capture/UIA) needs the Microsoft MFC runtime even
# when Python itself starts successfully. Install it inside the existing UAC flow.
if(!(Test-Path "$env:WINDIR\System32\mfc140u.dll")) {
 $redist=Join-Path $env:TEMP ('dafeiyu-vc-'+[guid]::NewGuid().ToString()+'.exe')
 try {
  Invoke-WebRequest 'https://aka.ms/vc14/vc_redist.x64.exe' -OutFile $redist
  $installed=Start-Process $redist -ArgumentList '/install /quiet /norestart' -Wait -PassThru
  if($installed.ExitCode -notin @(0,3010)){throw "Visual C++ runtime installation failed: $($installed.ExitCode)"}
 } finally {Remove-Item $redist -Force -ErrorAction SilentlyContinue}
}
$source=Split-Path $PSScriptRoot -Parent
# End the installed interpreter before replacing its modules. Agreements remain
# in the existing database and the new service resumes them below.
$existing=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if($existing -and $existing.State -eq 'Running'){Stop-ScheduledTask -TaskName $TaskName}
New-Item "$Root\app" -ItemType Directory -Force | Out-Null
foreach($folder in @('focus_demo','deploy')) {Copy-Item "$source\$folder" "$Root\app" -Recurse -Force}
Copy-Item "$source\dsh-plugin\default-prompts.json" "$Root\app\focus_demo\default_prompts.json" -Force
Copy-Item "$source\dsh-plugin\assets" "$Root\app" -Recurse -Force
if(!(Test-Path "$Root\venv\Scripts\python.exe")) {& $pythonPath -m venv "$Root\venv";if($LASTEXITCODE){throw 'venv failed'}}
& "$Root\venv\Scripts\python.exe" -m pip install -r "$source\requirements.txt"
if($LASTEXITCODE){throw "backend dependencies failed"}
& "$Root\venv\Scripts\python.exe" -I "$Root\app\deploy\retire_legacy.py" "$Root\app" "$env:USERPROFILE"
if($LASTEXITCODE){throw "retired browser observer cleanup failed"}
if($LASTEXITCODE){throw 'dependency installation failed'}
$config="$Root\config.json"
if(!(Test-Path $config)) {
 $bytes=New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $token=[Convert]::ToBase64String($bytes)
 @{data_dir="$Root\data";port=18769;token=$token;task_name=$TaskName;starter_task=($TaskName+'-Start');dsh_task=$DshTask;interval=600;sample=2} | ConvertTo-Json | Set-Content $config -Encoding UTF8
}
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$action=New-ScheduledTaskAction -Execute "$Root\venv\Scripts\pythonw.exe" -Argument "-I `"$Root\app\deploy\windows_service.py`" --config `"$config`""
$login=New-ScheduledTaskTrigger -AtLogOn -User $user
$retry=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Principal $principal -Action $action -Trigger @($login,$retry) -Settings $settings -Force | Out-Null
$startScript="$Root\start-supervisor.ps1"
@"
`$ErrorActionPreference='Stop'
Enable-ScheduledTask -TaskName '$TaskName' | Out-Null
Start-ScheduledTask -TaskName '$TaskName'
"@ | Set-Content $startScript -Encoding UTF8
$startAction=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
Register-ScheduledTask -TaskName ($TaskName+'-Start') -Principal $principal -Action $startAction -Settings $settings -Force | Out-Null
Enable-ScheduledTask -TaskName $TaskName | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed and started: $TaskName (python: $pythonPath). Existing agreements resume; no live agreement means automatic disable and exit."
