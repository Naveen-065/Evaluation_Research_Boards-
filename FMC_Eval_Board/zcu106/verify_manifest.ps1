$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$failures = @()
foreach ($line in Get-Content (Join-Path $root 'MANIFEST.sha256')) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
    $parts = $line -split '  ', 2
    if ($parts.Count -ne 2) { throw "Malformed manifest line: $line" }
    $path = Join-Path $root ($parts[1] -replace '/', [IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $failures += "missing: $($parts[1])"
        continue
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0]) { $failures += "hash mismatch: $($parts[1])" }
}
if ($failures.Count) { throw ($failures -join [Environment]::NewLine) }
Write-Host 'ZCU106 backup manifest verified.'
