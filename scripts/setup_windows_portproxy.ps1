# Run this in an admin PowerShell on the GPU server's Windows machine.
# Must be re-run after every reboot (WSL2 IP changes each time).
#
# Forwards the Windows LAN IP → WSL2 for:
#   port 22   — SSH (so you can reach WSL2 from your laptop)
#   port 8080 — HTTP app (students/professor on LAN)
#   port 8443 — HTTPS app (phones on LAN)

$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]
if (-not $wslIp) {
    Write-Host "ERROR: Could not detect WSL2 IP. Is Ubuntu running?" -ForegroundColor Red
    exit 1
}

Write-Host "WSL2 IP: $wslIp" -ForegroundColor Cyan

$ports = @(22, 8080, 8443)
foreach ($port in $ports) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
    netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

netsh advfirewall firewall delete rule name="transcriber" 2>$null
netsh advfirewall firewall add    rule name="transcriber" dir=in action=allow protocol=TCP localport=22,8080,8443

$winIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|172\.)' } | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "Done. Current portproxy rules:" -ForegroundColor Green
netsh interface portproxy show all
Write-Host ""
Write-Host "SSH into WSL2 from your laptop:"
Write-Host "  ssh <username>@$winIp"
Write-Host ""
Write-Host "App URLs (once server is started):"
Write-Host "  http://${winIp}:8080/?view   (students - LAN)"
Write-Host "  https://${winIp}:8443/?view  (phones - LAN HTTPS)"
