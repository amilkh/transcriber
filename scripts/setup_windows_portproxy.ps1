# Run this ONCE in an admin PowerShell on takelab's Windows machine.
# It forwards takelab's LAN IP (10.10.5.59) ports 8080 to WSL2.
# After this anyone on the classroom WiFi can open http://10.10.5.59:8080

$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]
if (-not $wslIp) { $wslIp = "172.28.250.189" }  # fallback

Write-Host "WSL2 IP: $wslIp"

netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8080 2>$null
netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=8080 connectaddress=$wslIp connectport=8080

netsh advfirewall firewall delete rule name="transcriber-8080" 2>$null
netsh advfirewall firewall add    rule name="transcriber-8080" dir=in action=allow protocol=TCP localport=8080

Write-Host ""
Write-Host "Done. Anyone on the LAN can now open:"
Write-Host "  http://10.10.5.59:8080        (teacher - full mic)"
Write-Host "  http://10.10.5.59:8080/?view  (students - transcript only)"
