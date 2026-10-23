# Перехресна перевірка бухгалтерії: проганяє сценарій через lib\Ledger.ps1 і друкує JSON
# з бітами результатів (Int64 від double), щоб порівняти з app\core\ledger.py до біта.
# Сценарій: { steps: [ { op: 'snap', earnedAtomic, units, workers: [ {name, work} ] } | { op: 'close' } | { op: 'export' } | { op: 'import', code } | { op: 'reset' } ] }
param([string]$ScenarioFile, [string]$LedgerPath)

$ErrorActionPreference = 'Stop'
$Test = $true
function ConvertTo-Hash($o) {
    if ($o -is [Management.Automation.PSCustomObject]) {
        $h = @{}
        foreach ($p in $o.PSObject.Properties) { $h[$p.Name] = ConvertTo-Hash $p.Value }
        return $h
    }
    $o
}
function Save-Stats {}
function Save-Settings {}
function Get-LocalWorkerName($coin) { [string]$coin.worker }
$PoolAdapters = @{ herominers = @{ Info = @{ Name = 'HeroMiners' } } }
$Settings = @{ WorkerOwners = @{} }
$script:Coins = @()
$script:Stats = @{ ledger = @{}; payouts = @(); local = @{} }
. $LedgerPath

$coin = [pscustomobject]@{ id = 'x'; ticker = 'PRL'; wallet = 'w1'; worker = 'me'; pool = [pscustomobject]@{ type = 'herominers'; coin = 'pearl' } }
$sc = Get-Content $ScenarioFile -Raw -Encoding UTF8 | ConvertFrom-Json
$out = @{ codes = @(); results = @() }
foreach ($s in @($sc.steps)) {
    switch ($s.op) {
        'snap' {
            # Нараховане — ціле в атомарних одиницях / units: однаковий double в обох мовах
            $earned = [double][long]$s.earnedAtomic / [double][long]$s.units
            $ws = @($s.workers | ForEach-Object { @{ name = [string]$_.name; work = [double][long]$_.work } })
            Add-PoolLedger $coin @{ earned = $earned; workExact = $true; workers = $ws }
        }
        'close' { Close-LedgerPeriod }
        'export' { $out.codes += Export-LedgerCode }
        'import' { Import-LedgerCode ([string]$s.code) | Out-Null }
        'reset' { $script:Stats = @{ ledger = @{}; payouts = @(); local = @{} } }
    }
    $L = $script:Stats.ledger[(Get-PoolLedgerKey $coin)]
    if ($L) {
        $r = Get-LedgerCoins $L
        $bits = @{}
        foreach ($n in $r.Names) { $bits[$n] = [string][BitConverter]::DoubleToInt64Bits($r.Coins[$n]) }
        $out.results += @{ bits = $bits; dist = [string][BitConverter]::DoubleToInt64Bits($r.Distributed) }
    } else { $out.results += @{ bits = @{}; dist = '0' } }
}
$out | ConvertTo-Json -Depth 6 -Compress
