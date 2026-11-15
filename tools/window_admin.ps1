param(
    [ValidateSet('Click','Inspect','Invoke','Capture','SetCheckbox','Close')][string]$Action = 'Inspect',
    [string]$Title = 'BlueStacks',
    [int]$TargetPid = 0,
    [double]$X = 0,
    [double]$Y = 0,
    [string]$ButtonName = '',
    [int]$CheckboxIndex = 0,
    [ValidateSet(0,1)][int]$DesiredState = 0,
    [string]$Output = 'C:\Users\Dirvi\AppData\Local\Temp\opencode\mirage-admin-ui.json',
    [string]$Capture = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MirageWindow {
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int left,top,right,bottom; }
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int x,y; }
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c,string n);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h,out RECT r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h,ref POINT p);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,UIntPtr w,IntPtr l);
}
'@
[MirageWindow]::SetProcessDPIAware() | Out-Null
$result = [ordered]@{ action=$Action; title=$Title; errors=@() }
try {
    $handle = [MirageWindow]::FindWindow($null,$Title)
    $windowPid = [uint32]0
    $element = $null
    if ($handle -ne [IntPtr]::Zero) {
        [MirageWindow]::GetWindowThreadProcessId($handle,[ref]$windowPid) | Out-Null
        $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    } else {
        $player = if ($TargetPid) { Get-Process -Id $TargetPid } else { Get-Process -Name HD-Player | Select-Object -First 1 }
        $windowPid = $player.Id
        $handle = $player.MainWindowHandle
        $condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$windowPid)
        $roots = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)
        $nameCondition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$Title)
        foreach ($root in $roots) {
            if ($root.Current.Name -eq $Title) { $element = $root; break }
            $candidate = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$nameCondition)
            if ($candidate) { $element=$candidate; break }
        }
        if (-not $element) { throw 'Window not found in accessibility tree' }
    }
    $result.process = $windowPid
    $bounds = $element.Current.BoundingRectangle
    $result.bounds = @{x=$bounds.X;y=$bounds.Y;width=$bounds.Width;height=$bounds.Height}
    if ($Action -eq 'Close') {
        $nativeHandle = [IntPtr]$element.Current.NativeWindowHandle
        if ($nativeHandle -eq [IntPtr]::Zero) { $nativeHandle=$handle }
        $result.closeRequested = [MirageWindow]::PostMessage($nativeHandle,16,[UIntPtr]::Zero,[IntPtr]::Zero)
    }
    if ($Action -eq 'Click') {
        if ($X -lt 0 -or $X -gt 1 -or $Y -lt 0 -or $Y -gt 1) { throw 'Invalid fractional coordinates' }
        $point = [MirageWindow+POINT]::new()
        $point.x = [int]($bounds.X + $bounds.Width * $X)
        $point.y = [int]($bounds.Y + $bounds.Height * $Y)
        $previous = [MirageWindow+POINT]::new()
        [MirageWindow]::GetCursorPos([ref]$previous) | Out-Null
        [MirageWindow]::SetForegroundWindow($handle) | Out-Null
        [MirageWindow]::SetCursorPos($point.x,$point.y) | Out-Null
        [MirageWindow]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
        [MirageWindow]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
        $result.point = @{x=$point.x;y=$point.y}
    }
    if ($Action -eq 'Invoke') {
        $condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$ButtonName)
        $button = $element.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition)
        if (-not $button) { throw 'Button not found' }
        $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
    }
    if ($Action -eq 'SetCheckbox') {
        $condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::CheckBox)
        $checkboxes = @($element.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition) | Sort-Object {$_.Current.BoundingRectangle.Y})
        if ($CheckboxIndex -ge $checkboxes.Count) { throw 'Checkbox index out of range' }
        $pattern = $checkboxes[$CheckboxIndex].GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        if ([int]$pattern.Current.ToggleState -ne $DesiredState) { $pattern.Toggle() }
        $result.toggleState = [int]$pattern.Current.ToggleState
    }
    if ($Action -eq 'Inspect') {
        $result.elements = @($element.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object {
            @{name=$_.Current.Name;type=$_.Current.ControlType.ProgrammaticName;enabled=$_.Current.IsEnabled;id=$_.Current.AutomationId;bounds=@{x=$_.Current.BoundingRectangle.X;y=$_.Current.BoundingRectangle.Y;width=$_.Current.BoundingRectangle.Width;height=$_.Current.BoundingRectangle.Height};patterns=@($_.GetSupportedPatterns() | ForEach-Object {$_.ProgrammaticName})}
        })
    }
    if ($Capture) {
        $python = Join-Path (Split-Path $PSScriptRoot) '.venv\Scripts\python.exe'
        & $python (Join-Path $PSScriptRoot 'capture_window.py') $windowPid $Capture
        $result.capture = $Capture
    }
} catch { $result.errors += $_.Exception.Message }
[IO.File]::WriteAllText($Output,($result | ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
