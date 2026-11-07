from datetime import datetime
import json
import subprocess

def schedule_status():
    command = "$t = Get-ScheduledTask -TaskName 'tradesea-asia' -ErrorAction SilentlyContinue; if ($t) { " \
              "$i = $t | Get-ScheduledTaskInfo; @{enabled=($t.State -ne 'Disabled'); next=$i.NextRunTime.ToString('s')} | ConvertTo-Json -Compress }"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        value = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
        if value and value["enabled"]:
            return "Next run: " + datetime.fromisoformat(value["next"]).strftime("%a, %b %d at %I:%M %p").replace(" 0", " ") + " (local)"
        return "Scheduled task is disabled" if value else "Scheduled task is not installed"
    except Exception:
        return "Schedule status unavailable"



def ensure_schedule(executable=None, runner=None):
    """Register this user's local-clock task without running it now."""
    from pathlib import Path
    import os
    import sys
    if executable is None:
        if not getattr(sys, 'frozen', False):
            raise RuntimeError('Open the packaged TradeSeaAsia.exe to enable automatic scheduling.')
        executable = sys.executable
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise RuntimeError('The application executable could not be found.')
    command = r'''
$ErrorActionPreference = 'Stop'
$exe = $env:TRADESEA_SCHEDULE_EXE
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$old = Get-ScheduledTask -TaskName 'tradesea-asia' -ErrorAction SilentlyContinue
if ($old) {
    $owner = $old.Principal.UserId
    if ($owner -ne $user.User.Value) {
        $account = New-Object System.Security.Principal.NTAccount($owner)
        if ($account.Translate([System.Security.Principal.SecurityIdentifier]).Value -ne $user.User.Value) {
            throw 'The existing tradesea-asia task belongs to another Windows user.'
        }
    }
    if (@($old.Actions).Count -ne 1 -or [IO.Path]::GetFileName($old.Actions[0].Execute) -ne 'TradeSeaAsia.exe' -or $old.Actions[0].Arguments -ne '--run') {
        throw 'An unrelated task already uses the tradesea-asia name.'
    }
}
$next = [datetime]::Today.AddHours(17)
while ($next -le [datetime]::Now -or $next.DayOfWeek -eq 'Friday' -or $next.DayOfWeek -eq 'Saturday') { $next = $next.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday,Monday,Tuesday,Wednesday,Thursday -At $next
$trigger.StartBoundary = $next.ToString('yyyy-MM-ddTHH:mm:ss')
$action = New-ScheduledTaskAction -Execute $exe -Argument '--run' -WorkingDirectory ([IO.Path]::GetDirectoryName($exe))
$principal = New-ScheduledTaskPrincipal -UserId $user.User.Value -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'tradesea-asia' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'TradeSea automatic lockouts: Sunday-Thursday at 5 PM system-local time.' -Force | Out-Null
$t = Get-ScheduledTask -TaskName 'tradesea-asia'
if ($t.State -eq 'Disabled' -or $t.Actions[0].Execute -ne $exe) { throw 'Task registration could not be verified.' }
'''
    env = dict(os.environ, TRADESEA_SCHEDULE_EXE=str(executable))
    result = (runner or subprocess.run)(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW, env=env)
    if result.returncode:
        raise RuntimeError((result.stderr or 'Windows rejected task registration.').strip())
