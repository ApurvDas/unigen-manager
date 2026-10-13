# Bluetooth helper for Unigen Manager. bt.py runs this text through winrun.ps(); inputs arrive in $p (UM_ARGS JSON).
# $p.action: radios | enable | disable. Output: one JSON document.

function Radios {
  $out = @(foreach ($d in Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match '^(USB|PCI)\\' }) {
    $lmp = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Bluetooth_RadioLmpVersion -ErrorAction SilentlyContinue).Data
    if ($null -eq $lmp) { continue }  # not a radio (e.g. a USB composite child)
    [pscustomobject]@{ id = $d.InstanceId; name = $d.FriendlyName; status = "$($d.Status)"; problem = "$($d.Problem)"; lmp = [int]$lmp }
  })
  ConvertTo-Json -InputObject $out -Compress
}

switch ($p.action) {
  'radios'  { Radios }
  'enable'  { Enable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'disable' { Disable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  default   { throw "Unknown action: $($p.action)" }
}
