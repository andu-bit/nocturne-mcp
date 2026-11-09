# Determine script location and .env path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $scriptDir "..\.env"

# Load .env file
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([^#=]+)\s*=\s*(.*)\s*$") {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
        }
    }
}
else {
    Write-Error ".env file not found at $envFile"
    exit 1
}

# Configuration
$dbmsPath = "C:\Users\niwatori\.Neo4jDesktop2\Data\dbmss\dbms-06876a16-8151-4cfa-87aa-acc5edc75007"
$cypherShell = "$dbmsPath\bin\cypher-shell.bat"
$importDir = "$dbmsPath\import"
$backupDir = Join-Path $scriptDir "..\backups"

# Use Neo4j's bundled JDK (cypher-shell.bat uses JAVACMD, not JAVA_HOME)
$neo4jJdkPath = "C:\Users\niwatori\.Neo4jDesktop2\Cache\runtime\zulu21.44.17-ca-jdk21.0.8-win_x64"
$javaExe = "$neo4jJdkPath\bin\java.exe"
if (Test-Path $javaExe) {
    $env:JAVACMD = $javaExe
    Write-Host "Using Neo4j bundled JDK: $javaExe" -ForegroundColor Gray
}
else {
    Write-Error "Neo4j bundled JDK not found at $javaExe. Please install Java 21."
    exit 1
}

# Get credentials from environment
$user = [Environment]::GetEnvironmentVariable("dbuser")
$pass = [Environment]::GetEnvironmentVariable("dbpassword")

if ([string]::IsNullOrWhiteSpace($user) -or [string]::IsNullOrWhiteSpace($pass)) {
    Write-Error "Credentials (dbuser, dbpassword) not found in .env file"
    exit 1
}

# Ensure backup directory exists
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

Write-Host "Starting Memory Backup..." -ForegroundColor Cyan

# 1. Execute Export via Cypher Shell
$exportQuery = 'CALL apoc.export.cypher.all("memory_backup.cypher", {format: "plain", useOptimizations: {type: "UNWIND_BATCH", unwindBatchSize: 20}});'

Write-Host "Exporting database to local import folder..."
echo $exportQuery | & $cypherShell -u $user -p $pass --address "localhost:12000"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Export successful." -ForegroundColor Green
}
else {
    Write-Error "Export failed. check if database is running."
}

# 2. Move and Rename
$sourceFile = "$importDir\memory_backup.cypher"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$destFile = "$backupDir\memory_backup_$timestamp.cypher"

if (Test-Path $sourceFile) {
    Move-Item -Path $sourceFile -Destination $destFile -Force
    Write-Host "Backup saved to: $destFile" -ForegroundColor Yellow
}
else {
    Write-Error "Source file not found: $sourceFile"
}
