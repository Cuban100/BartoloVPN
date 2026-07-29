# BartoloVPN bootstrap installer for Windows.
# Detects/installs Python (via winget, falling back to a direct download
# from python.org if winget isn't available), then hands off to the real
# Python-based setup script (vpn-setup.py).

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "BartoloVPN Installer"
Write-Host "===================="

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            try {
                $verOutput = & $cmd --version 2>&1
                if ($verOutput -match "Python (\d+)\.(\d+)") {
                    $major = [int]$Matches[1]
                    $minor = [int]$Matches[2]
                    if ($major -eq 3 -and $minor -ge 8) {
                        return $cmd
                    }
                }
            } catch {}
        }
    }
    return $null
}

function Install-Winget {
    Write-Host "winget not found - installing it automatically..."
    $bundlePath = Join-Path $env:TEMP "Microsoft.DesktopAppInstaller.msixbundle"
    try {
        Invoke-WebRequest -Uri "https://aka.ms/getwinget" -OutFile $bundlePath
        Add-AppxPackage -Path $bundlePath
    } catch {
        Write-Host "WARNING: Automatic winget install failed: $_"
        return $false
    } finally {
        if (Test-Path $bundlePath) { Remove-Item $bundlePath -ErrorAction SilentlyContinue }
    }
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Install-PythonDirect {
    Write-Host "Downloading the official python.org installer directly..."
    try {
        $releases = Invoke-RestMethod -Uri "https://endoflife.date/api/python.json"
        $version = $releases[0].latest
    } catch {
        $version = "3.12.7"  # known-good fallback if the API is unreachable
    }

    $installerUrl = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-$version-amd64.exe"

    Write-Host "Downloading Python $version..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath

    Write-Host "Running installer silently..."
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait

    Remove-Item $installerPath -ErrorAction SilentlyContinue
}

function Install-Python {
    Write-Host "Python 3.8+ not found - installing it automatically..."

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Install-Winget | Out-Null
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python via winget..."
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    } else {
        Install-PythonDirect
    }

    # Refresh PATH for the current session so the new install is visible
    # without needing to reopen the terminal
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Install-Python
    $pythonCmd = Find-Python
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Failed to install Python automatically."
    Write-Host "Please install Python 3.8+ manually from https://www.python.org/downloads/ and re-run this script."
    exit 1
}

Write-Host "Using: $(& $pythonCmd --version)"
Write-Host ""
& $pythonCmd vpn-setup.py @args
exit $LASTEXITCODE
