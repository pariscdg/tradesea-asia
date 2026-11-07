# Align the existing task with Asia open using the Windows local system clock.
$ErrorActionPreference = 'Stop'
Get-ScheduledTask -TaskName 'tradesea-asia' | Out-Null
$asiaLocalTrigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Sunday,Monday,Tuesday,Wednesday,Thursday -At ([datetime]::Today.AddHours(17))
# Explicitly omit the offset: the cmdlet otherwise serializes today's UTC offset.
$asiaLocalTrigger.StartBoundary = [datetime]::Today.AddHours(17).ToString('yyyy-MM-ddTHH:mm:ss')
Set-ScheduledTask -TaskName 'tradesea-asia' -Trigger $asiaLocalTrigger | Out-Null
$asiaSavedTrigger = (Get-ScheduledTask -TaskName 'tradesea-asia').Triggers[0]
if ($asiaSavedTrigger.StartBoundary -match '(Z|[+-]\d\d:\d\d)$') {
    throw 'The schedule unexpectedly retained a fixed UTC offset.'
}
Get-ScheduledTaskInfo -TaskName 'tradesea-asia' | Select-Object NextRunTime
