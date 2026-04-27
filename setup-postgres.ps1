# setup-postgres.ps1
# Run this script once as Administrator to:
#   1. Set the postgres user password to "bankbot2024"
#   2. Create the bankbot database
#   3. Enable the pgvector extension
#
# Right-click PowerShell -> "Run as Administrator", then:
#   cd "g:\_era\Era_BI-dev_v2\Era_BI-dev_v2\Demo_Project"
#   .\setup-postgres.ps1

$ErrorActionPreference = "Stop"
$psql      = "C:\Program Files\PostgreSQL\16\bin\psql.exe"
$pg_ctl    = "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe"
$data      = "C:\Program Files\PostgreSQL\16\data"
$hba       = "$data\pg_hba.conf"
$newPass   = "bankbot2024"

Write-Host "== Step 1: Switching pg_hba.conf to trust auth ==" -ForegroundColor Cyan
$hbaContent = Get-Content $hba -Raw
$hbaContent -replace 'scram-sha-256', 'trust' | Set-Content $hba -Encoding UTF8

Write-Host "== Step 2: Restarting PostgreSQL ==" -ForegroundColor Cyan
Restart-Service postgresql-x64-16
Start-Sleep -Seconds 3

Write-Host "== Step 3: Setting postgres password and creating database ==" -ForegroundColor Cyan
$sql = @"
ALTER USER postgres WITH PASSWORD '$newPass';
SELECT 'password set' AS result;
"@
$sql | & $psql -U postgres -h 127.0.0.1 -p 5432

$sql2 = @"
SELECT 'exists' FROM pg_database WHERE datname='bankbot';
"@
$exists = ($sql2 | & $psql -U postgres -h 127.0.0.1 -p 5432 -t).Trim()
if ($exists -ne 'exists') {
    "CREATE DATABASE bankbot;" | & $psql -U postgres -h 127.0.0.1 -p 5432
    Write-Host "Database 'bankbot' created." -ForegroundColor Green
} else {
    Write-Host "Database 'bankbot' already exists." -ForegroundColor Yellow
}

Write-Host "== Step 4: Enabling pgvector extension ==" -ForegroundColor Cyan
"CREATE EXTENSION IF NOT EXISTS vector;" | & $psql -U postgres -h 127.0.0.1 -p 5432 -d bankbot

Write-Host "== Step 5: Restoring scram-sha-256 auth ==" -ForegroundColor Cyan
$hbaContent -replace 'scram-sha-256', 'trust' | Set-Content $hba -Encoding UTF8
(Get-Content $hba -Raw) -replace 'trust', 'scram-sha-256' | Set-Content $hba -Encoding UTF8
Restart-Service postgresql-x64-16
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "== Done! ==" -ForegroundColor Green
Write-Host "Postgres password: $newPass"
Write-Host "Update backend\.env with:"
Write-Host "  POSTGRES_URL=postgresql+asyncpg://postgres:$newPass@localhost:5432/bankbot"
Write-Host ""
Write-Host "Then restart uvicorn."
