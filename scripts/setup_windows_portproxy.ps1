# Run in an admin PowerShell on the GPU server's Windows machine.
# Phase 1 (first run): installs WSL2 + Ubuntu, then reboots.
# Phase 2 (after reboot): checks NVIDIA driver, sets up SSH in WSL2, portproxy + firewall.
# After phase 2 you can do everything else over SSH from your laptop.

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

# ── NVIDIA driver check ──────────────────────────────────────────────────────

$nvidiaSmi = wsl -d Ubuntu -- nvidia-smi 2>&1
if ($nvidiaSmi -match "NVIDIA-SMI") {
    Write-Host "NVIDIA driver: OK" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "WARNING: nvidia-smi not found in WSL2." -ForegroundColor Yellow
    Write-Host "Install the latest NVIDIA driver (Windows version) from:" -ForegroundColor Yellow
    Write-Host "  https://www.nvidia.com/Download/index.aspx" -ForegroundColor Cyan
    Write-Host "WSL2 inherits it automatically — no separate Linux driver needed." -ForegroundColor Yellow
    Write-Host "Re-run this script after installing." -ForegroundColor Yellow
    Write-Host ""
}

# ── Phase 2: SSH + portproxy ─────────────────────────────────────────────────

# Install SSH, generate host keys (fixes 'connection reset' on first run), start SSH
Write-Host "Setting up SSH server in WSL2..." -ForegroundColor Cyan
wsl -d Ubuntu -- bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server zstd && sudo ssh-keygen -A && sudo service ssh restart && grep -q 'service ssh' ~/.bashrc || echo 'sudo service ssh start 2>/dev/null' >> ~/.bashrc"

# Get WSL2 IP
$wslIp = (wsl -d Ubuntu -- ip addr show eth0 2>$null | Select-String "inet ").ToString().Trim().Split()[1].Split("/")[0]
if (-not $wslIp) {
    Write-Host "ERROR: Could not detect WSL2 IP. Make sure Ubuntu is running." -ForegroundColor Red
    exit 1
}
Write-Host "WSL2 IP: $wslIp" -ForegroundColor Cyan

# Portproxy: Windows LAN -> WSL2 for SSH, HTTP, HTTPS
foreach ($port in @(22, 8080, 8443)) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
    netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

# Firewall
netsh advfirewall firewall delete rule name="transcriber" 2>$null
netsh advfirewall firewall add    rule name="transcriber" dir=in action=allow protocol=TCP localport=22,8080,8443

# ── Keep WSL2 alive when screen is locked ────────────────────────────────────
# WSL2 can be suspended when Windows locks, killing SSH and all processes.
# This scheduled task runs at startup and on unlock, keeping a WSL process alive.

$taskName  = "WSL2-KeepAlive"
$taskAction = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -- sleep infinity"
$triggers  = @(
    $(New-ScheduledTaskTrigger -AtStartup),
    $(New-ScheduledTaskTrigger -AtLogOn)
)
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Write-Host "WSL2 keep-alive task registered and started." -ForegroundColor Green

# ── Detect Windows LAN IP ─────────────────────────────────────────────────────
$winIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notmatch '^(127\.|172\.|169\.)'
} | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "All done." -ForegroundColor Green
Write-Host ""
Write-Host "From your laptop, SSH in with:" -ForegroundColor White
Write-Host "  ssh <username>@$winIp" -ForegroundColor Yellow
Write-Host ""
Write-Host "App URLs once the server is running:" -ForegroundColor White
Write-Host "  http://${winIp}:8080/?view   (students - LAN)"
Write-Host "  https://${winIp}:8443/?view  (phones  - LAN HTTPS)"
