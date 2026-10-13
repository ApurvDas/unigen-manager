# Adapter helper for Unigen Manager. hw.py runs this text through winrun.ps(); inputs arrive in $p (UM_ARGS JSON).
# $p.action: devices | enable | disable. Output: one JSON document.

function Devices {
  $out = @(foreach ($d in Get-PnpDevice -PresentOnly -Class Net,Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match '^(USB|PCI)\' }) {
    [pscustomobject]@{ id = $d.InstanceId; name = $d.FriendlyName; status = "$($d.Status)"; problem = "$($d.Problem)" }
  })
  ConvertTo-Json -InputObject $out -Compress
}

switch ($p.action) {
  'devices' { Devices }
  'enable'  { Enable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'disable' { Disable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  default   { throw "Unknown action: $($p.action)" }
}
