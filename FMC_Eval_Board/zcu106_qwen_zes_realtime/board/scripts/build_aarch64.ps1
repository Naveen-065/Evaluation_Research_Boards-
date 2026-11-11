param(
    [string]$Compiler = 'C:\Xilinx\Vitis\2022.2\gnu\aarch64\nt\aarch64-linux\bin\aarch64-linux-gnu-gcc.exe'
)

$ErrorActionPreference = 'Stop'
$boardDir = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $boardDir 'build'
$source = Join-Path $boardDir 'src\zes_relay.c'
$includeDir = Join-Path $boardDir 'include'
$vendorDir = Join-Path $boardDir 'vendor\zes'
$vendorLib = Join-Path $vendorDir 'zesEDAC_LN_AA64_NV_v1.3.0_b01_release.a'
$output = Join-Path $buildDir 'zes-edac-relay'
$expectedLibraryHash = 'B8192785CD3466DC491B1EEAF8DA8BE98BC4FE0A40FF6688D248D3A675BE03B4'
$expectedHeaderHash = '1C14E54C4A0545350B28AEDE434CADBF9076BE2E019CC0F5D4CCF554B4129375'

if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "AArch64 compiler not found: $Compiler"
}

$libraryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $vendorLib).Hash
$headerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $vendorDir 'zesEdacV130.h')).Hash
if ($libraryHash -ne $expectedLibraryHash) {
    throw "Vendor library hash mismatch: $libraryHash"
}
if ($headerHash -ne $expectedHeaderHash) {
    throw "Vendor header hash mismatch: $headerHash"
}

New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

$arguments = @(
    '-I', $includeDir,
    '-I', $vendorDir,
    '-std=c11',
    '-O2',
    '-g',
    '-Wall',
    '-Wextra',
    '-Wpedantic',
    '-Werror',
    '-static',
    '-o', $output,
    $source,
    $vendorLib
)

& $Compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "AArch64 link failed with exit code $LASTEXITCODE"
}

$toolDir = Split-Path -Parent $Compiler
$readelf = Join-Path $toolDir 'aarch64-linux-gnu-readelf.exe'
if (Test-Path -LiteralPath $readelf -PathType Leaf) {
    & $readelf '-h' $output
    if ($LASTEXITCODE -ne 0) {
        throw "readelf verification failed with exit code $LASTEXITCODE"
    }
}

Get-Item -LiteralPath $output | Select-Object FullName, Length
Get-FileHash -Algorithm SHA256 -LiteralPath $output
