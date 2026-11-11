param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._:-]+$')]
    [string]$Target,

    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$User = 'root',

    [ValidatePattern('^/[A-Za-z0-9._/-]+$')]
    [string]$InstallDir = '/opt/zes-edac-relay'
)

$ErrorActionPreference = 'Stop'
$boardDir = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $boardDir 'build/zes-edac-relay'
$service = Join-Path $boardDir 'systemd/zes-edac-relay.service'
$remote = "${User}@${Target}"

if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    throw "AArch64 relay not found at $binary. Run scripts/build_aarch64.sh in Linux/WSL first."
}

ssh $remote "mkdir -p '$InstallDir'"
scp $binary "${remote}:${InstallDir}/zes-edac-relay"
scp $service "${remote}:/tmp/zes-edac-relay.service"
ssh $remote "chmod 0755 '$InstallDir/zes-edac-relay' && install -m 0644 /tmp/zes-edac-relay.service /etc/systemd/system/zes-edac-relay.service && systemctl daemon-reload && systemctl enable --now zes-edac-relay.service"
ssh $remote "systemctl --no-pager --full status zes-edac-relay.service"
