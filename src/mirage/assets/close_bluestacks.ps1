param([Parameter(Mandatory=$true)][int]$Port)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
try {
    if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid ADB port' }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' })
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1) { throw 'Ambiguous BlueStacks listener' }
    $player = Get-Process -Id $owners[0]
    if ($player.ProcessName -ne 'HD-Player') { throw 'ADB port does not belong to BlueStacks' }
    if ($player.MainWindowHandle -eq 0) { throw 'BlueStacks window is not available' }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($player.MainWindowHandle)
    $window.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close()
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (-not $player.HasExited) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'BlueStacks window did not close' }
        try {
            $condition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::Button)
            $buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
            foreach ($button in $buttons) {
                $name = $button.Current.Name
                # Russian names are constructed without a script encoding dependency.
                $ruClose = -join @(0x417,0x430,0x43a,0x440,0x44b,0x442,0x44c | ForEach-Object { [char]$_ })
                if ($name -eq $ruClose -or $name -in @('Close','Exit','Quit')) {
                    $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                    break
                }
            }
        } catch [System.Windows.Automation.ElementNotAvailableException] {
            # The process can disappear between checking HasExited and querying UIA.
        }
        $player.WaitForExit(150) | Out-Null
    }
    Write-Output 'BlueStacks process closed normally'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
