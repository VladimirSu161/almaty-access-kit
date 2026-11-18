# Комплект 1.0.0: запуск общего Linux-сеанса в выделенном WSL2. Проверки выполняются на ПК получателя.
[CmdletBinding()]
param(
    [switch]$Experimental,
    [switch]$Plan,
    [string]$Distro = 'AlmatyAccess',
    [string]$LinuxUser,
    [string]$LinuxLauncher,
    [string]$Project,
    [string]$State,
    [string]$Cli,
    [string]$CliSha256,
    [string]$ChromeDir,
    [string]$SshSocket,
    [int]$SshPid,
    [string]$ServerIp,
    [string]$KnownHosts,
    [string]$HostKeySha256,
    [string]$AuthFile,
    [string]$WaylandSocket,
    [ValidateSet('cli', 'browser', 'both')]
    [string]$Apps = 'both'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

try {
    if ($Distro -notmatch '^AlmatyAccess(?:-[A-Za-z0-9_-]+)?$') {
        throw 'Разрешён только выделенный стенд AlmatyAccess или AlmatyAccess-имя.'
    }
    if ($LinuxUser -notmatch '^[a-z_][a-z0-9_-]*$' -or $LinuxUser -eq 'root') {
        throw 'Укажи непривилегированного пользователя именно этого стенда.'
    }
    $Paths = @($LinuxLauncher, $Project, $State, $Cli, $ChromeDir, $SshSocket, $KnownHosts, $AuthFile)
    if ($Apps -ne 'cli') { $Paths += $WaylandSocket }
    foreach ($Item in $Paths) {
        # Windows native argv не должен неоднозначно кодировать кавычки/контрольные символы.
        if ([string]::IsNullOrWhiteSpace($Item) -or -not $Item.StartsWith('/') -or
            $Item -match '[\x00-\x1f\x7f"\\]' -or $Item -match '(^|/)\.\.(/|$)') {
            throw 'Нужны абсолютные Linux-пути без .., кавычек, обратных слешей и управляющих символов.'
        }
    }
    if ($CliSha256 -notmatch '^[0-9a-f]{64}$' -or $HostKeySha256 -notmatch '^SHA256:[A-Za-z0-9+/]{43}$' -or $SshPid -le 1) {
        throw 'Нужны проверенные hash CLI, host-key fingerprint и PID SSH.'
    }
    $ParsedIp = $null
    if (-not [System.Net.IPAddress]::TryParse($ServerIp, [ref]$ParsedIp) -or
        $ParsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Нужен числовой IPv4 своего VPS.'
    }
    $LinuxArguments = @('/usr/bin/python3', '-I', '-B', $LinuxLauncher, '--apps', $Apps,
        '--project', $Project, '--state', $State, '--cli', $Cli, '--cli-sha256', $CliSha256,
        '--chrome-dir', $ChromeDir, '--ssh-socket', $SshSocket, '--ssh-pid', [string]$SshPid,
        '--server-ip', $ServerIp, '--known-hosts', $KnownHosts, '--host-key-sha256', $HostKeySha256,
        '--auth-file', $AuthFile)
    if ($Apps -ne 'cli') { $LinuxArguments += @('--wayland-socket', $WaylandSocket) }
    $WslArguments = @('--distribution', $Distro, '--user', $LinuxUser, '--exec') + $LinuxArguments
    if ($Plan) {
        # Даже WSL не запускается: старт distro мог бы активировать её службы SSH.
        @{scope='guided-plan-only'; production_ready=$false; runtime_verified=$false;
          executable='wsl.exe'; argv=$WslArguments; note='Только план. WSL не запускался.'} |
            ConvertTo-Json -Depth 5
        exit 0
    }
    if ($env:OS -ne 'Windows_NT') { throw 'Runtime wrapper работает только в Windows 11.' }
    if ([System.Environment]::OSVersion.Version.Build -lt 22000) { throw 'Нужна Windows 11; Windows 10 не проверяется этим wrapper.' }
    $Wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    if (-not (Test-Path -LiteralPath $Wsl -PathType Leaf)) { throw 'WSL не установлен. Ничего автоматически не устанавливается.' }
    $Inventory = & $Wsl --list --verbose
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось прочитать список WSL.' }
    $DistroPattern = '^\s*\*?\s*' + [regex]::Escape($Distro) + '\s+.+\s+2\s*$'
    $Found = @($Inventory | Where-Object { (($_ -replace "`0", '').TrimEnd()) -match $DistroPattern })
    if ($Found.Count -ne 1) { throw 'Не найден ровно один выбранный дистрибутив WSL2. Default distro не используется.' }
    # Нет shell, Invoke-Expression, bash -c, default distro, Windows browser или fallback.
    & $Wsl @WslArguments
    exit $LASTEXITCODE
} catch {
    Write-Error ('СТОП: ' + $_.Exception.Message + ' Обычный Claude/браузер не запускался.') -ErrorAction Continue
    exit 78
}
