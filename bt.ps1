# Bluetooth helper for Unigen Manager. bt.py runs this text through winrun.ps(); inputs arrive in $p (UM_ARGS JSON).
# $p.action: enable | disable (device lists come from pnp.py). Output: one JSON document.

switch ($p.action) {
  'enable'  { Enable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  'disable' { Disable-PnpDevice -InstanceId $p.id -Confirm:$false; '{"ok":true}' }
  default   { throw "Unknown action: $($p.action)" }
}
