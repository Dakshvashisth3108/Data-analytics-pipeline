# =========================================================================
# setup_java21.ps1 -- install OpenJDK 21 LTS for Spark.
#
# Why this exists:
#   Spark 4.x ships Hadoop 3.4.1 which calls Subject.getSubject() during
#   UserGroupInformation init. Java 24+ permanently disabled that method,
#   so Spark crashes on Java 24/25/26. Hadoop 3.4.2 fixes it -- but no
#   released Spark bundles 3.4.2 yet.
#
#   Java 21 LTS is the latest Java where Subject.getSubject() still works,
#   AND it's officially supported by Spark 4.x.
#
# This script:
#   1. Downloads OpenJDK 21 (tries multiple mirrors, retries with BITS).
#   2. Extracts to  C:\java\jdk21\
#   3. Writes  scripts\spark-env.ps1  -- a tiny shim you dot-source to
#      switch JAVA_HOME for the current shell only. System-default Java
#      stays untouched.
# =========================================================================

$ErrorActionPreference = "Stop"

$InstallRoot = "C:\java"
$JdkDir      = Join-Path $InstallRoot "jdk21"
$ZipPath     = Join-Path $InstallRoot "openjdk21.zip"

# Mirror order: Microsoft (usually fastest for Windows), then Adoptium.
$Mirrors = @(
    @{ name = "Microsoft OpenJDK";     url = "https://aka.ms/download-jdk/microsoft-jdk-21.0.5-windows-x64.zip" },
    @{ name = "Microsoft OpenJDK alt"; url = "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip" },
    @{ name = "Adoptium Temurin";      url = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.5%2B11/OpenJDK21U-jdk_x64_windows_hotspot_21.0.5_11.zip" }
)

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

if (-not (Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
}

$javaExe = Join-Path $JdkDir "bin\java.exe"
if (Test-Path $javaExe) {
    Write-Host "==> JDK 21 already installed at $JdkDir"
} else {
    # Try BITS (resumable, more robust against drops); fall back to IWR.
    function Try-BITS($url, $dst) {
        try {
            Import-Module BitsTransfer -ErrorAction Stop
        } catch {
            return $false
        }
        try {
            Start-BitsTransfer -Source $url -Destination $dst -DisplayName "JDK21" -ErrorAction Stop
            return (Test-Path $dst) -and ((Get-Item $dst).Length -gt 50MB)
        } catch {
            Write-Host ("       BITS failed: " + $_.Exception.Message) -ForegroundColor Yellow
            if (Test-Path $dst) { Remove-Item $dst -Force -ErrorAction SilentlyContinue }
            return $false
        }
    }

    function Try-IWR($url, $dst) {
        try {
            $params = @{
                Uri                = $url
                OutFile            = $dst
                UseBasicParsing    = $true
                TimeoutSec         = 600
                MaximumRedirection = 10
            }
            Invoke-WebRequest @params
            return (Test-Path $dst) -and ((Get-Item $dst).Length -gt 50MB)
        } catch {
            Write-Host ("       IWR failed: " + $_.Exception.Message) -ForegroundColor Yellow
            if (Test-Path $dst) { Remove-Item $dst -Force -ErrorAction SilentlyContinue }
            return $false
        }
    }

    $downloaded = $false
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

    foreach ($mirror in $Mirrors) {
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            Write-Host ""
            Write-Host "==> Downloading from $($mirror.name) (attempt $attempt)"
            Write-Host "    $($mirror.url)"
            if (Try-BITS $mirror.url $ZipPath) {
                Write-Host "    [BITS OK]"
                $downloaded = $true; break
            }
            if (Try-IWR $mirror.url $ZipPath) {
                Write-Host "    [IWR OK]"
                $downloaded = $true; break
            }
            Start-Sleep -Seconds (3 * $attempt)
        }
        if ($downloaded) { break }
    }

    if (-not $downloaded) {
        Write-Host ""
        Write-Host "ERROR: could not download JDK 21 from any mirror." -ForegroundColor Red
        Write-Host ""
        Write-Host "Manual fallback (paste into a browser):"
        Write-Host "  https://learn.microsoft.com/en-us/java/openjdk/download"
        Write-Host "Pick 'Microsoft Build of OpenJDK 21 LTS' Windows x64 zip,"
        Write-Host "save it as $ZipPath, then re-run this script."
        exit 1
    }

    $size = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "==> Downloaded $size MB"
    Write-Host "==> Extracting to $JdkDir ..."

    $tmpExtract = Join-Path $InstallRoot "_jdk21_tmp"
    if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
    Expand-Archive -Path $ZipPath -DestinationPath $tmpExtract -Force

    $inner = Get-ChildItem -Path $tmpExtract -Directory | Select-Object -First 1
    if ($null -eq $inner) {
        throw "Unexpected zip layout -- no inner JDK directory found"
    }
    if (Test-Path $JdkDir) { Remove-Item $JdkDir -Recurse -Force }
    Move-Item -Path $inner.FullName -Destination $JdkDir
    Remove-Item $tmpExtract -Recurse -Force
    Remove-Item $ZipPath -Force
}

Write-Host ""
Write-Host "==> Verifying:"
& $javaExe -version

# Write the shim
$shim = Join-Path (Split-Path -Parent $PSCommandPath) "spark-env.ps1"
@"
# Dot-source this script BEFORE running Spark jobs:
#     . .\scripts\spark-env.ps1
#     python -m bronze.ingest_employee_stream --once
#
# Switches JAVA_HOME to JDK 21 only for this shell.
# System-default Java is unchanged.
`$env:JAVA_HOME = '$JdkDir'
`$env:Path = (Join-Path `$env:JAVA_HOME 'bin') + ';' + `$env:Path
Write-Host "spark-env.ps1: JAVA_HOME=`$env:JAVA_HOME"
"@ | Set-Content -Path $shim -Encoding ascii

Write-Host ""
Write-Host "Done."
Write-Host "  JDK installed:  $JdkDir"
Write-Host "  Activation:     . .\scripts\spark-env.ps1"
Write-Host ""
Write-Host "Run Spark jobs like this from now on:"
Write-Host "  . .\scripts\spark-env.ps1"
Write-Host "  python -m bronze.ingest_employee_stream --once"
