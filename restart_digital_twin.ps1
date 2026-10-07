$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$baseUrl = 'http://127.0.0.1:8000'

function Get-ProjectListener {
    Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

$listener = Get-ProjectListener
if ($listener) {
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
    } catch {
        throw "Port 8000 is occupied, but the process does not expose the current Digital Twin health endpoint. No process was stopped. Press Ctrl+C in the PowerShell window that started that server, wait for port 8000 to become free, then run this script again."
    }

    if ($health.service_id -ne 'traffic-digital-twin') {
        throw "Port 8000 is occupied by a service that is not identified as this Digital Twin. No process was stopped."
    }

    Write-Host "[Server] Requesting graceful shutdown of the Digital Twin on port 8000..."
    try {
        $null = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/control/shutdown" -TimeoutSec 3
    } catch {
        throw "The Digital Twin refused graceful shutdown. No process was stopped. Detail: $($_.Exception.Message)"
    }

    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $listener = Get-ProjectListener
    } while ($listener -and (Get-Date) -lt $deadline)

    if ($listener) {
        throw "The Digital Twin did not release port 8000 within 20 seconds. No process was killed; inspect its original console."
    }
    Write-Host '[Server] Old server exited and SUMO shutdown hooks completed.'
} else {
    Write-Host '[Server] Port 8000 is free.'
}

Write-Host '[Server] Starting the current workspace source. Keep this terminal open; press Ctrl+C for a graceful stop.'
python -m python.main
exit $LASTEXITCODE
