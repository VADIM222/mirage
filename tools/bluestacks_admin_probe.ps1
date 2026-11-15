param(
    [string]$Instance = 'Nougat64',
    [string]$Output = 'C:\Users\Dirvi\AppData\Local\Temp\opencode\mirage-bluestacks-admin.json'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$result = [ordered]@{ administrator = $false; instance = $Instance; errors = @() }
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $result.administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $config = [IO.File]::ReadAllText('C:\ProgramData\BlueStacks_nxt\bluestacks.conf')
    $escaped = [regex]::Escape($Instance)
    $match = [regex]::Match($config, "bst\.instance\.$escaped\.status\.adb_port=`"(\d+)`"")
    if (-not $match.Success) { throw 'No current ADB port in BlueStacks configuration' }
    $serial = '127.0.0.1:' + $match.Groups[1].Value
    $adb = 'C:\Program Files\BlueStacks_nxt\HD-Adb.exe'
    $result.serial = $serial
    $result.connect = (& $adb -P 5041 connect $serial 2>&1 | Out-String).Trim()
    $result.devices = (& $adb -P 5041 devices -l 2>&1 | Out-String).Trim()
    $result.shell = (& $adb -P 5041 -s $serial shell 'id; getprop ro.product.cpu.abi; getprop ro.build.version.release; command -v su; su -c id' 2>&1 | Out-String).Trim()
} catch {
    $result.errors += $_.Exception.Message
} finally {
    [IO.File]::WriteAllText($Output, ($result | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
}
