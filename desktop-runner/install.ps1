# Afaq Tuwaiq work-computer runner — installer (no secrets inside; the device token is entered by you on first run
# and stored in Windows Credential Manager).
$ErrorActionPreference = 'Stop'
$Base = 'https://gulf-logistics-ai-v7-production.up.railway.app/agent-runner/client'
$Dir = Join-Path $env:LOCALAPPDATA 'AfaqRunner\app'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Write-Host 'تثبيت جهاز آفاق طويق...' -ForegroundColor Cyan

function Find-Python {
  foreach ($c in @('py -3.12', 'python')) {
    try { $v = & cmd /c "$c --version" 2>$null; if ($v -match 'Python 3\.(1[1-9])') { return $c } } catch {}
  }
  return $null
}
$py = Find-Python
if (-not $py) {
  Write-Host 'تثبيت Python 3.12...' -ForegroundColor Yellow
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')
  $py = Find-Python
  if (-not $py) { throw 'تعذر تثبيت Python تلقائيًا. ثبّته من python.org ثم أعد تشغيل هذا الأمر.' }
}
foreach ($f in @('afaq_runner.py','requirements.txt')) { Invoke-WebRequest -UseBasicParsing "$Base/$f" -OutFile (Join-Path $Dir $f) }
$req = Join-Path $Dir 'requirements.txt'
& cmd /c "$py -m pip install --user -q -r `"$req`""
& cmd /c "$py -m playwright install chromium"
$launcher = Join-Path $Dir 'start.cmd'
$update = "powershell -NoProfile -Command `"try { Invoke-WebRequest -UseBasicParsing '$Base/afaq_runner.py' -OutFile afaq_runner.py.new; Move-Item -Force afaq_runner.py.new afaq_runner.py } catch {}`""
"@echo off`r`nchcp 65001 >nul`r`ncd /d `"$Dir`"`r`n$update`r`n$py afaq_runner.py`r`npause" | Set-Content -Encoding ascii $launcher
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'جهاز آفاق طويق.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath = $launcher; $s.WorkingDirectory = $Dir; $s.Save()
Write-Host 'تم التثبيت. افتح اختصار «جهاز آفاق طويق» على سطح المكتب والصق رمز الجهاز عند الطلب.' -ForegroundColor Green
