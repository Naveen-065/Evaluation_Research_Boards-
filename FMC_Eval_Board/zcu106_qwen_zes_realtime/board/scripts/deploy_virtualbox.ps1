#requires -Version 5.1

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidatePattern('^[A-Za-z0-9._ -]+$')]
    [string]$VmName = 'Ubuntu-20.04-MPSoC-OS',

    [System.Management.Automation.PSCredential]$Credential,

    [ValidateRange(1, 8)]
    [int]$NatAdapter = 1,

    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$NatRuleName = 'zes-edac',

    [ValidateRange(1, 65535)]
    [int]$HostPort = 9106,

    [switch]$VerifyOnly,

    [string]$VBoxManagePath = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
)

$ErrorActionPreference = 'Stop'
$ExpectedRelaySha256 = 'DDD47DE47769900DF0CAC2025DA546231DF5047E81C3325AE04335953089F1C0'
$ExpectedVendorVersion = '1.3.0'
$GuestPort = 9106
$InstallDir = '/opt/zes-edac-relay'
$GuestBinary = "$InstallDir/zes-edac-relay"
$GuestService = '/etc/systemd/system/zes-edac-relay.service'
$ServiceName = 'zes-edac-relay.service'

function Invoke-VBoxManage {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AcceptedExitCodes = @(0)
    )

    $output = & $VBoxManagePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($AcceptedExitCodes -notcontains $exitCode) {
        throw "VBoxManage failed with exit code ${exitCode}: $($output -join [Environment]::NewLine)"
    }
    return ($output -join [Environment]::NewLine).Trim()
}

function Invoke-GuestProgram {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @(),
        [int[]]$AcceptedExitCodes = @(0),
        [int]$TimeoutMilliseconds = 600000
    )

    if (-not $script:GuestSession) {
        throw 'Internal error: VirtualBox guest session is not open.'
    }
    Write-Verbose "Guest run: $Executable"
    $guestProcess = $null
    try {
        [string[]]$processArguments = @($Executable) + $Arguments
        $guestProcess = $script:GuestSession.ProcessCreate(
            $Executable,
            $processArguments,
            [string[]]@(),
            [int[]]@(0),
            [uint32]$TimeoutMilliseconds
        )
        # VirtualBox reports missing executables and guest-service failures as
        # Error or Down. Treat those as terminal so prerequisite probes can
        # react immediately instead of waiting for the command timeout.
        $terminalStatuses = @(500, 510, 511, 512, 513, 600, 800)
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        while ($guestProcess.Status -notin $terminalStatuses) {
            if ($stopwatch.ElapsedMilliseconds -ge $TimeoutMilliseconds) {
                try { $guestProcess.Terminate() } catch {}
                throw "Guest program timed out after $TimeoutMilliseconds ms: $Executable"
            }
            Start-Sleep -Milliseconds 50
        }
        $terminalStatus = [int]$guestProcess.Status
        if ($terminalStatus -ne 500) {
            throw "Guest program terminated abnormally: $Executable (status=$terminalStatus)."
        }
        $exitCode = [int]$guestProcess.ExitCode
        if ($AcceptedExitCodes -notcontains $exitCode) {
            throw "Guest program failed with exit code ${exitCode}: $Executable"
        }
        return [PSCustomObject]@{ ExitCode = $exitCode }
    } finally {
        if ($guestProcess) {
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($guestProcess) | Out-Null } catch {}
        }
        Write-Verbose "Guest complete: $Executable"
    }
}

function Copy-ToGuest {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not $script:GuestSession) {
        throw 'Internal error: VirtualBox guest session is not open.'
    }
    Write-Verbose "Guest copy: $(Split-Path -Leaf $Source) -> $Destination"
    $progress = $null
    try {
        $progress = $script:GuestSession.FileCopyToGuest($Source, $Destination, [int[]]@(0))
        [void]$progress.WaitForCompletion(600000)
        if (-not $progress.Completed -or $progress.ResultCode -ne 0) {
            throw "VirtualBox guest copy failed: $Source -> $Destination (result=$($progress.ResultCode))."
        }
    } finally {
        if ($progress) {
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($progress) | Out-Null } catch {}
        }
    }
}

function Get-GuestSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not $script:GuestSession.FileExists($Path, $true)) {
        return $null
    }
    $guestFile = $null
    $sha256 = $null
    try {
        $guestFile = $script:GuestSession.FileOpen($Path, 1, 1, 0)
        $size = [int64]$guestFile.QuerySize()
        $offset = [int64]0
        $sha256 = [Security.Cryptography.SHA256]::Create()
        while ($offset -lt $size) {
            $toRead = [uint32][Math]::Min(65536, $size - $offset)
            [byte[]]$chunk = $guestFile.ReadAt($offset, $toRead, 10000)
            if ($chunk.Count -eq 0) {
                throw "Unexpected EOF while hashing guest file $Path at offset $offset."
            }
            [void]$sha256.TransformBlock($chunk, 0, $chunk.Count, $chunk, 0)
            $offset += $chunk.Count
        }
        [void]$sha256.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return ([BitConverter]::ToString($sha256.Hash) -replace '-', '')
    } finally {
        if ($guestFile) {
            try { $guestFile.Close() } catch {}
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($guestFile) | Out-Null } catch {}
        }
        if ($sha256) {
            $sha256.Dispose()
        }
    }
}

function Test-QemuAarch64Binfmt {
    try {
        $qemuParameters = @{
            Executable        = '/usr/bin/qemu-aarch64-static'
            Arguments         = @('--version')
            AcceptedExitCodes = @(0, 1)
        }
        $qemu = Invoke-GuestProgram @qemuParameters
    } catch {
        Write-Verbose "qemu-aarch64 prerequisite probe failed: $($_.Exception.Message)"
        return $false
    }
    if ($qemu.ExitCode -ne 0) {
        return $false
    }
    try {
        $binfmtParameters = @{
            Executable        = '/bin/grep'
            Arguments         = @('-q', '^enabled', '/proc/sys/fs/binfmt_misc/qemu-aarch64')
            AcceptedExitCodes = @(0, 1, 2)
        }
        $binfmt = Invoke-GuestProgram @binfmtParameters
    } catch {
        Write-Verbose "qemu-aarch64 binfmt probe failed: $($_.Exception.Message)"
        return $false
    }
    return $binfmt.ExitCode -eq 0
}

function Get-NatForwardingRules {
    param([Parameter(Mandatory = $true)][string]$MachineInfo)

    $rules = @()
    foreach ($line in ($MachineInfo -split "`r?`n")) {
        if ($line -match '^Forwarding\(\d+\)="(.*)"$') {
            $fields = $Matches[1].Split(',')
            if ($fields.Count -eq 6) {
                $rules += [PSCustomObject]@{
                    Name      = $fields[0]
                    Protocol  = $fields[1]
                    HostIp    = $fields[2]
                    HostPort  = [int]$fields[3]
                    GuestIp   = $fields[4]
                    GuestPort = [int]$fields[5]
                    Raw       = $Matches[1]
                }
            }
        }
    }
    return $rules
}

function Read-Exact {
    param(
        [Parameter(Mandatory = $true)][System.IO.Stream]$Stream,
        [Parameter(Mandatory = $true)][int]$Length
    )

    $buffer = New-Object byte[] $Length
    $offset = 0
    while ($offset -lt $Length) {
        $count = $Stream.Read($buffer, $offset, $Length - $offset)
        if ($count -le 0) {
            throw "The ZES relay closed the connection after $offset of $Length bytes."
        }
        $offset += $count
    }
    return $buffer
}

function Read-UInt32BigEndian {
    param([byte[]]$Buffer, [int]$Offset)

    return [uint32]((([uint32]$Buffer[$Offset]) -shl 24) -bor
        (([uint32]$Buffer[$Offset + 1]) -shl 16) -bor
        (([uint32]$Buffer[$Offset + 2]) -shl 8) -bor
        ([uint32]$Buffer[$Offset + 3]))
}

function Test-ZesInfo {
    param([Parameter(Mandatory = $true)][int]$Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $connection.Wait(5000)) {
            throw "Timed out connecting to the ZES relay on 127.0.0.1:$Port."
        }
        # The relay is intentionally single-client. Allow its 30-second idle
        # client timeout to expire if the GUI left a connection open.
        $client.ReceiveTimeout = 35000
        $client.SendTimeout = 5000
        $stream = $client.GetStream()
        [byte[]]$request = @(0x5A, 0x45, 0x53, 0x31, 0x01, 0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x5A, 0x45, 0x53, 0x31)
        $stream.Write($request, 0, $request.Length)
        $header = Read-Exact -Stream $stream -Length 16
        if ([Text.Encoding]::ASCII.GetString($header, 0, 4) -ne 'ZES1' -or
            $header[4] -ne 1 -or $header[5] -ne 0x81) {
            throw 'The service returned an invalid ZES1 INFO header.'
        }
        $payloadLength = [int](Read-UInt32BigEndian -Buffer $header -Offset 8)
        if ($payloadLength -lt 12 -or $payloadLength -gt 256) {
            throw "The service returned invalid INFO payload length $payloadLength."
        }
        $payload = Read-Exact -Stream $stream -Length $payloadLength
        $status = Read-UInt32BigEndian -Buffer $payload -Offset 0
        if ($status -ne 0) {
            throw "The ZES INFO request failed with status $status."
        }
        $dataBytes = Read-UInt32BigEndian -Buffer $payload -Offset 4
        $parityBytes = Read-UInt32BigEndian -Buffer $payload -Offset 8
        $version = [Text.Encoding]::UTF8.GetString($payload, 12, $payloadLength - 12)
        if ($dataBytes -ne 1024 -or $parityBytes -ne 72) {
            throw "Unexpected vendor geometry: data=$dataBytes, parity=$parityBytes."
        }
        return [PSCustomObject]@{
            DataBytes   = $dataBytes
            ParityBytes = $parityBytes
            Version     = $version
        }
    } finally {
        $client.Dispose()
    }
}

$boardDir = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $boardDir 'build\zes-edac-relay'
$service = Join-Path $boardDir 'systemd\zes-edac-relay.service'

if (-not (Test-Path -LiteralPath $VBoxManagePath -PathType Leaf)) {
    throw "VBoxManage was not found at $VBoxManagePath."
}
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    throw "AArch64 relay not found at $binary. Run scripts/build_aarch64.ps1 first."
}
if (-not (Test-Path -LiteralPath $service -PathType Leaf)) {
    throw "Systemd unit not found at $service."
}

$savedWhatIfPreference = $WhatIfPreference
try {
    # Windows PowerShell 5.1 propagates the script's WhatIf preference into
    # provider-backed reads. Disable it only around these non-mutating hashes.
    $WhatIfPreference = $false
    $localBinarySha = (Get-FileHash -Algorithm SHA256 -LiteralPath $binary).Hash.ToUpperInvariant()
    $localServiceSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $service).Hash.ToUpperInvariant()
} finally {
    $WhatIfPreference = $savedWhatIfPreference
}
if ($localBinarySha -ne $ExpectedRelaySha256) {
    throw "Refusing to deploy relay SHA-256 $localBinarySha; expected pinned build $ExpectedRelaySha256."
}

$machineInfo = Invoke-VBoxManage -Arguments @('showvminfo', $VmName, '--machinereadable')
if ($machineInfo -notmatch '(?m)^VMState="running"\r?$') {
    throw "VirtualBox VM '$VmName' is not running. Start it, wait for Guest Additions, and retry."
}
$natAdapterPattern = '(?m)^nic{0}="nat"\r?$' -f $NatAdapter
if ($machineInfo -notmatch $natAdapterPattern) {
    throw "Adapter $NatAdapter on '$VmName' is not configured as NAT."
}

$rules = @(Get-NatForwardingRules -MachineInfo $machineInfo)
$endpointRule = $rules | Where-Object {
    $_.Protocol -eq 'tcp' -and $_.HostIp -eq '127.0.0.1' -and
    $_.HostPort -eq $HostPort -and $_.GuestPort -eq $GuestPort
} | Select-Object -First 1
$namedRule = $rules | Where-Object { $_.Name -eq $NatRuleName } | Select-Object -First 1

Write-Host "VM: $VmName (running, NAT adapter $NatAdapter)"
Write-Host "Pinned relay SHA-256: $localBinarySha"

if ($WhatIfPreference) {
    [void]$PSCmdlet.ShouldProcess($VmName, "deploy and enable $ServiceName inside the guest")
    if (-not $endpointRule) {
        [void]$PSCmdlet.ShouldProcess($VmName, "configure 127.0.0.1:$HostPort -> guest:$GuestPort NAT forwarding")
    }
    Write-Host 'WhatIf preflight passed; no credential was requested and no guest or VM state was changed.'
    return
}

if (-not $endpointRule) {
    if ($VerifyOnly) {
        throw "Missing NAT forwarding rule 127.0.0.1:$HostPort -> guest:$GuestPort."
    }
    if ($namedRule -and $PSCmdlet.ShouldProcess($VmName, "replace conflicting NAT rule '$NatRuleName'")) {
        [void](Invoke-VBoxManage -Arguments @('controlvm', $VmName, "natpf$NatAdapter", 'delete', $NatRuleName))
    }
    $forwarding = "$NatRuleName,tcp,127.0.0.1,$HostPort,,$GuestPort"
    if ($PSCmdlet.ShouldProcess($VmName, "add NAT rule $forwarding")) {
        [void](Invoke-VBoxManage -Arguments @('controlvm', $VmName, "natpf$NatAdapter", $forwarding))
    }
}

if (-not $Credential) {
    $Credential = Get-Credential -UserName 'root' -Message "Root credential for VirtualBox guest '$VmName'"
}
if (-not $Credential) {
    throw 'A guest credential is required.'
}
if ($Credential.UserName -ne 'root') {
    throw "The deployment must run as guest user 'root' to install under /opt and manage systemd."
}

$virtualBox = $null
$machine = $null
$session = $null
$console = $null
$guest = $null
$script:GuestSession = $null
$passwordBstr = [IntPtr]::Zero

try {
    $virtualBox = New-Object -ComObject VirtualBox.VirtualBox
    $machine = $virtualBox.FindMachine($VmName)
    $session = New-Object -ComObject VirtualBox.Session
    $machine.LockMachine($session, 1)
    $console = $session.Console
    $guest = $console.Guest
    try {
        $passwordBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential.Password)
        $passwordText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordBstr)
        $script:GuestSession = $guest.CreateSession(
            $Credential.UserName,
            $passwordText,
            '',
            "zes-edac-deploy-$PID"
        )
        $passwordText = $null
    } finally {
        $passwordText = $null
        if ($passwordBstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordBstr)
            $passwordBstr = [IntPtr]::Zero
        }
    }
    $sessionWait = $script:GuestSession.WaitFor(1, 15000)
    if ($sessionWait -ne 1 -or $script:GuestSession.Status -ne 100) {
        throw "VirtualBox guest session failed to start (wait=$sessionWait, status=$($script:GuestSession.Status))."
    }

    $binfmtReady = Test-QemuAarch64Binfmt
    Write-Verbose "qemu-aarch64 binfmt ready: $binfmtReady"
if (-not $binfmtReady) {
    if ($VerifyOnly) {
        throw 'qemu-aarch64 binfmt is not enabled in the VM.'
    }
    if ($PSCmdlet.ShouldProcess($VmName, 'install and enable qemu-aarch64 binfmt support')) {
        [void](Invoke-GuestProgram -Executable '/usr/bin/apt-get' -Arguments @('update') -TimeoutMilliseconds 1200000)
        [void](Invoke-GuestProgram -Executable '/usr/bin/apt-get' -Arguments @('install', '-y', 'qemu-user-static', 'binfmt-support') -TimeoutMilliseconds 1200000)
        [void](Invoke-GuestProgram -Executable '/usr/sbin/update-binfmts' -Arguments @('--enable', 'qemu-aarch64'))
    }
}
if (-not (Test-QemuAarch64Binfmt)) {
    throw 'qemu-aarch64 binfmt is still unavailable after prerequisite handling.'
}

$guestBinarySha = Get-GuestSha256 -Path $GuestBinary
$guestServiceSha = Get-GuestSha256 -Path $GuestService
$binaryChanged = $guestBinarySha -ne $localBinarySha
$serviceChanged = $guestServiceSha -ne $localServiceSha

if ($VerifyOnly) {
    if ($binaryChanged) {
        throw "Guest relay SHA-256 is '$guestBinarySha'; expected $localBinarySha."
    }
    if ($serviceChanged) {
        throw "Guest systemd unit SHA-256 is '$guestServiceSha'; expected $localServiceSha."
    }
} else {
    if ($binaryChanged -and $PSCmdlet.ShouldProcess($GuestBinary, 'install pinned AArch64 ZES relay')) {
        $guestBinaryStage = "$InstallDir/.zes-edac-relay.deploy-$PID"
        [void](Invoke-GuestProgram -Executable '/usr/bin/install' -Arguments @('-d', '-m', '0755', $InstallDir))
        Copy-ToGuest -Source $binary -Destination $guestBinaryStage
        [void](Invoke-GuestProgram -Executable '/bin/chmod' -Arguments @('0755', $guestBinaryStage))
        $stagedSha = Get-GuestSha256 -Path $guestBinaryStage
        if ($stagedSha -ne $localBinarySha) {
            throw "Staged relay hash mismatch: guest=$stagedSha, local=$localBinarySha."
        }
        # The staging file is in the target directory, so rename(2) replaces
        # the executable atomically while the current service keeps its old
        # inode until the controlled systemd restart below.
        [void](Invoke-GuestProgram -Executable '/bin/mv' -Arguments @('-f', '--', $guestBinaryStage, $GuestBinary))
    }
    if ($serviceChanged -and $PSCmdlet.ShouldProcess($GuestService, 'install ZES relay systemd unit')) {
        Copy-ToGuest -Source $service -Destination '/tmp/zes-edac-relay.service'
        [void](Invoke-GuestProgram -Executable '/usr/bin/install' -Arguments @('-m', '0644', '/tmp/zes-edac-relay.service', $GuestService))
        [void](Invoke-GuestProgram -Executable '/bin/rm' -Arguments @('-f', '/tmp/zes-edac-relay.service'))
    }
    if ($PSCmdlet.ShouldProcess($VmName, "enable and start $ServiceName")) {
        if ($binaryChanged -or $serviceChanged) {
            [void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('daemon-reload'))
            [void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('enable', $ServiceName))
            [void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('restart', $ServiceName))
        } else {
            [void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('enable', '--now', $ServiceName))
        }
    }
}

$verifiedGuestSha = Get-GuestSha256 -Path $GuestBinary
if ($verifiedGuestSha -ne $localBinarySha) {
    throw "Post-deployment relay hash mismatch: guest=$verifiedGuestSha, local=$localBinarySha."
}
[void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('is-enabled', '--quiet', $ServiceName))
[void](Invoke-GuestProgram -Executable '/bin/systemctl' -Arguments @('is-active', '--quiet', $ServiceName))
$portHex = ('{0:X4}' -f $GuestPort)
[void](Invoke-GuestProgram -Executable '/bin/grep' -Arguments @('-Eq', ":${portHex}[[:space:]].*[[:space:]]0A[[:space:]]", '/proc/net/tcp'))

$info = Test-ZesInfo -Port $HostPort
if ($info.Version -ne $ExpectedVendorVersion) {
    throw "Unexpected ZES vendor version '$($info.Version)'; expected '$ExpectedVendorVersion'."
}
Write-Host "Guest SHA-256 verified: $verifiedGuestSha"
Write-Host "Systemd: enabled and active; guest TCP $GuestPort is listening"
Write-Host "Host relay: 127.0.0.1:$HostPort, ZES vendor $($info.Version), $($info.DataBytes)-byte data + $($info.ParityBytes)-byte parity"
Write-Host 'VirtualBox ZES EDAC deployment verified.'
} finally {
    if ($passwordBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordBstr)
    }
    if ($script:GuestSession) {
        try { $script:GuestSession.Close() } catch {}
    }
    if ($session) {
        try { $session.UnlockMachine() } catch {}
    }
    foreach ($comObject in @($script:GuestSession, $guest, $console, $session, $machine, $virtualBox)) {
        if ($comObject) {
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($comObject) | Out-Null } catch {}
        }
    }
    $script:GuestSession = $null
}
