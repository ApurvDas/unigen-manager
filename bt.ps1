# Bluetooth helper for Unigen Manager. bt.py runs this text through winrun.ps(); inputs arrive in $p (UM_ARGS JSON).
# $p.action: radios | enable | disable | paired | nearby | pair | unpair. Output: one JSON document.

function Radios {
  $out = @(foreach ($d in Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match '^(USB|PCI)\\' }) {
    $lmp = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Bluetooth_RadioLmpVersion -ErrorAction SilentlyContinue).Data
    if ($null -eq $lmp) { continue }  # not a radio (e.g. a USB composite child)
    [pscustomobject]@{ id = $d.InstanceId; name = $d.FriendlyName; status = "$($d.Status)"; problem = "$($d.Problem)"; lmp = [int]$lmp }
  })
  ConvertTo-Json -InputObject $out -Compress
}

function Winrt {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $script:asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $null = [Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime]
  $null = [Windows.Devices.Bluetooth.BluetoothDevice, Windows.Devices.Bluetooth, ContentType = WindowsRuntime]
}

function Await($op, [Type]$type) {
  $t = $script:asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $null = $t.Wait(-1)
  $t.Result
}

function List([bool]$paired) {
  Winrt
  $sel = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($paired)
  $all = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($sel)) ([Windows.Devices.Enumeration.DeviceInformationCollection])
  $out = @(foreach ($di in $all) {
    $dev = $null
    try { $dev = Await ([Windows.Devices.Bluetooth.BluetoothDevice]::FromIdAsync($di.Id)) ([Windows.Devices.Bluetooth.BluetoothDevice]) } catch { }
    [pscustomobject]@{
      id        = $di.Id
      name      = $di.Name
      connected = [bool]($dev -and "$($dev.ConnectionStatus)" -eq 'Connected')
      major     = if ($dev) { [int]$dev.ClassOfDevice.MajorClass } else { 0 }
      minor     = if ($dev) { [int]$dev.ClassOfDevice.MinorClass } else { 0 }
      address   = if ($dev) { '{0:X12}' -f $dev.BluetoothAddress } else { '' }
    }
  })
  ConvertTo-Json -InputObject $out -Compress
}

function Pairing([string]$action) {
  Winrt
  $di = Await ([Windows.Devices.Enumeration.DeviceInformation]::CreateFromIdAsync($p.id)) ([Windows.Devices.Enumeration.DeviceInformation])
  if ($action -eq 'pair') { $r = Await ($di.Pairing.PairAsync()) ([Windows.Devices.Enumeration.DevicePairingResult]) }
  else { $r = Await ($di.Pairing.UnpairAsync()) ([Windows.Devices.Enumeration.DeviceUnpairingResult]) }
  @{ status = "$($r.Status)" } | ConvertTo-Json -Compress
}

switch ($p.action) {
  'radios'  { Radios }
  'enable'  { Enable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'disable' { Disable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'paired'  { List $true }
  'nearby'  { List $false }
  'pair'    { Pairing 'pair' }
  'unpair'  { Pairing 'unpair' }
  default   { throw "Unknown action: $($p.action)" }
}
