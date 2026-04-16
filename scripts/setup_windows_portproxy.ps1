# Run in an admin PowerShell on the GPU server's Windows machine.
# Phase 1 (first run): installs WSL2 + Ubuntu, then reboots.
# Phase 2 (after reboot): starts SSH in WSL2, sets up portproxy + firewall.
# After this script completes you can do everything else over SSH from your laptop.

# ── Phase 1: WSL2 + Ubuntu ──────────────────────────────────────────────────

$ubuntuInstalled = (wsl -l -v 2>&1) -match "Ubuntu"

if (-not $ubuntuInstalled) {
    Write-Host "Installing WSL2 + Ubuntu..." -ForegroundColor Cyan
    wsl --install -d Ubuntu
    Write-Host ""
    Write-Host "Reboot required. After reboot, open Ubuntu from the Start menu to" -ForegroundColor Yellow
    Write-Host "create your Linux username/password, then re-run this script." -ForegroundColor Yellow
    pause
    Restart-Computer
    exit
}

# ── Phase 2: SSH + portproxy ─────────────────────────────────────────────────

# Ensure Ubuntu is running and SSH is installed + started
Write-Host "Starting SSH server in WSL2..." -ForegroundColor Cyan
wsl -d Ubuntu -- bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server zstd && sudo service ssh start && echo 'sudo service ssh start 2>/dev/null' >> ~/.bashrc" 2>&1

# Get WSL2 IP
$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]
if (-not $wslIp) {
    Write-Host "ERROR: Could not detect WSL2 IP. Make sure Ubuntu is running." -ForegroundColor Red
    exit 1
}
Write-Host "WSL2 IP: $wslIp" -ForegroundColor Cyan

# Portproxy: Windows LAN -> WSL2 for SSH, HTTP, HTTPS
$ports = @(22, 8080, 8443)
foreach ($port in $ports) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
    netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

# Firewall rules
netsh advfirewall firewall delete rule name="transcriber" 2>$null
netsh advfirewall firewall add    rule name="transcriber" dir=in action=allow protocol=TCP localport=22,8080,8443

# Detect Windows LAN IP (exclude loopback and WSL2 ranges)
$winIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notmatch '^(127\.|172\.|169\.)'
} | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "All done." -ForegroundColor Green
Write-Host ""
Write-Host "From your laptop, SSH in with:" -ForegroundColor White
Write-Host "  ssh <username>@$winIp" -ForegroundColor Yellow
Write-Host ""
Write-Host "Then from SSH, finish the setup (clone repo, install deps, etc.)" -ForegroundColor White
Write-Host ""
Write-Host "App URLs once the server is running:" -ForegroundColor White
Write-Host "  http://${winIp}:8080/?view   (students - LAN)"
Write-Host "  https://${winIp}:8443/?view  (phones  - LAN HTTPS)"
