# ---- Бухгалтерія: скільки монет намайнив кожен воркер і кожен власник ----
# stats.json → ledger: { "<тип пулу>|<монета пулу>|<гаманець>": рахунок }, payouts: [ видачі ].
#
# Розподіл однаковий на всіх ПК і не залежить від того, коли панель опитувала пул:
#   у пулу накопичувальні лічильники роботи воркерів (HeroMiners: hashes — сума складності шар;
#   Kryptex: кількість шар, тому «≈») і накопичене нараховане на гаманець (виплачено + баланс).
#   Контрольна точка (КТ) фіксує { Earned, Counters, Coins } на момент закриття періоду, далі
#     монети воркера = КТ.Coins + (Earned − КТ.Earned) × робота воркера після КТ / уся робота після КТ.
#   Тож однакова КТ + та сама відповідь пулу = ті самі числа, а поки панель вимкнена, нічого
#   не губиться: лічильники ростуть на пулі. КТ передається іншим учасникам кодом (без сервера).
#   КТ зберігається цілими числами: EarnedQ і CoinsQ — у нано-монетах (×10⁹), Counters — цілі.
#   Дробові числа ConvertFrom-Json у PowerShell 5.1 читає через decimal і інколи губить останній
#   біт, а цілі читаються точно — тож КТ однакова до біта на всіх ПК (і в app\core\ledger.py).
#
# Рахунок: Ticker, Pool, Wallet, Exact; Cp — КТ; Raw — останні лічильники пулу (воркери, що
#   зникли з пулу, лишаються з останнім значенням); Base — від якого значення лічильника йде
#   поточний відрізок; Acc — робота відрізків до скидання лічильника; Resets — коли пул скинув
#   лічильник (на інших ПК цього могли не бачити → треба закрити період); Earned, Time, Hr, Online,
#   Unconfirmed — остання відповідь пулу.
# Файл підключається до MinerPanel.ps1 (dot-source) після lib\Stats.ps1.

$LedgerRefreshMin   = 10       # інші рахунки (не поточна монета) — не частіше ніж раз на 10 хв
$LedgerCodePrefix   = 'MPK1:'
$script:LedgerJob   = $null
$script:LedgerNext  = Get-Date
$script:LedgerError = $null

function Get-PoolLedgerKey($coin) { "$($coin.pool.type)|$($coin.pool.coin)|$($coin.wallet)" }

# Ключі хеш-таблиці у сталому порядку — щоб суми на всіх ПК додавались однаково.
# Ординально (за кодами символів), як sorted() у новій версії app\core\ledger.py, а не за мовою ОС
function Get-SortedKeys($h) {
    [string[]]$k = @($h.Keys | ForEach-Object { [string]$_ })
    [Array]::Sort($k, [StringComparer]::Ordinal)
    $k
}
function Copy-Hash($h) { $c = @{}; if ($h) { foreach ($k in @($h.Keys)) { $c[$k] = $h[$k] } }; $c }

# Нано-монети: ціле ↔ дробове (Math.Round, як і round() у Python, округлює до парного)
$LedgerScale = 1e9
function ConvertTo-LedgerQ([double]$x) { [long][Math]::Round($x * $LedgerScale) }
function ConvertFrom-LedgerQ($q) { [double][long]$q / $LedgerScale }
function ConvertTo-LedgerCounters($h) { $c = @{}; if ($h) { foreach ($n in @($h.Keys)) { $c[$n] = [long][Math]::Round([double]$h[$n]) } }; $c }

# КТ у цілих числах; КТ першої версії (Earned, Coins — дробові) переводиться в нову форму
function Repair-LedgerCp($cp) {
    if ($null -eq $cp.EarnedQ) { $cp.EarnedQ = ConvertTo-LedgerQ ([double]$cp.Earned); $cp.Remove('Earned') }
    if (-not ($cp.CoinsQ -is [hashtable])) {
        $q = @{}
        if ($cp.Coins -is [hashtable]) { foreach ($n in @($cp.Coins.Keys)) { $q[$n] = ConvertTo-LedgerQ ([double]$cp.Coins[$n]) } }
        $cp.CoinsQ = $q; $cp.Remove('Coins')
    } else {
        foreach ($n in @($cp.CoinsQ.Keys)) { $cp.CoinsQ[$n] = [long]$cp.CoinsQ[$n] }
    }
    $cp.EarnedQ = [long]$cp.EarnedQ
    $cp.Counters = ConvertTo-LedgerCounters $cp.Counters
    $cp
}

function New-LedgerAccount([string]$ticker, [string]$pool, [string]$wallet, [bool]$exact) {
    @{ Ticker = $ticker; Pool = $pool; Wallet = $wallet; Exact = $exact
       Cp = @{ Time = (Get-Date).ToString('o'); EarnedQ = [long]0; Counters = @{}; CoinsQ = @{} }
       Raw = @{}; Base = @{}; Acc = @{}; Resets = @{}; Hr = @{}; Online = @{}
       Earned = 0.0; Time = $null; Unconfirmed = 0.0 }
}

# Старий журнал (stats.json → pool) → рахунок з КТ на момент його останнього нарахування:
# лічильники тоді = Work − Pending, тож наступний приріст ділиться так само, як ділив би старий
function ConvertFrom-OldLedger($L) {
    $a = New-LedgerAccount ([string]$L.Ticker) ([string]$L.Pool) ([string]$L.Wallet) ([bool]$L.Exact)
    if ($L.Since) { $a.Cp.Time = [string]$L.Since }
    $a.Cp.EarnedQ = ConvertTo-LedgerQ ([double]$L.Earned)
    foreach ($n in @($L.Coins.Keys)) { $a.Cp.CoinsQ[$n] = ConvertTo-LedgerQ ([double]$L.Coins[$n]) }
    foreach ($n in @($L.Work.Keys)) {
        $a.Cp.Counters[$n] = [long][Math]::Max(0.0, [double]$L.Work[$n] - [double]$L.Pending[$n])
        $a.Raw[$n] = [double]$L.Work[$n]
    }
    foreach ($n in @($a.Cp.Counters.Keys)) { $a.Base[$n] = [double]$a.Cp.Counters[$n] }
    $a.Earned = [double]$L.Earned
    $a
}

# Після завантаження stats.json: КТ у нову форму, службові таблиці на місці
function Repair-LedgerAccounts {
    foreach ($L in @($script:Stats.ledger.Values)) {
        if (-not ($L.Cp -is [hashtable])) { $L.Cp = @{ Time = (Get-Date).ToString('o') } }
        Repair-LedgerCp $L.Cp | Out-Null
        foreach ($k in 'Raw', 'Base', 'Acc', 'Resets', 'Hr', 'Online') { if (-not ($L[$k] -is [hashtable])) { $L[$k] = @{} } }
    }
}

function Get-LedgerAccount($coin, [bool]$exact) {
    $key = Get-PoolLedgerKey $coin
    $L = $script:Stats.ledger[$key]
    if (-not $L) {
        $pa = $PoolAdapters[[string]$coin.pool.type]
        $L = New-LedgerAccount ([string]$coin.ticker) $(if ($pa) { [string]$pa.Info.Name } else { [string]$coin.pool.type }) ([string]$coin.wallet) $exact
        $script:Stats.ledger[$key] = $L
    }
    foreach ($k in 'Raw', 'Base', 'Acc', 'Resets', 'Hr', 'Online') { if (-not ($L[$k] -is [hashtable])) { $L[$k] = @{} } }
    $L
}

# Відповідь пулу ($d з адаптера pools\*.ps1: earned, workExact, workers[].name/work/hr3h/online)
function Add-PoolLedger($coin, $d) {
    if ($null -eq $d.earned -or -not $coin.wallet -or -not $coin.ticker) { return }
    $L = Get-LedgerAccount $coin ([bool]$d.workExact)
    $L.Exact = [bool]$d.workExact
    $now = (Get-Date).ToString('o')
    foreach ($w in @($d.workers)) {
        if (-not $w -or -not $w.name) { continue }
        $n = [string]$w.name
        $raw = [double]$w.work
        if (-not $L.Base.ContainsKey($n)) { $L.Base[$n] = $(if ($L.Cp.Counters.ContainsKey($n)) { [double]$L.Cp.Counters[$n] } else { 0.0 }) }
        if ($L.Raw.ContainsKey($n) -and $raw -lt [double]$L.Raw[$n]) {
            # Пул скинув лічильник: зароблене до скидання зберігаємо, далі рахуємо від нуля
            $L.Acc[$n] = [double]$L.Acc[$n] + [Math]::Max(0.0, [double]$L.Raw[$n] - [double]$L.Base[$n])
            $L.Base[$n] = 0.0
            $L.Resets[$n] = $now
        } elseif ($raw -lt [double]$L.Base[$n]) {
            # Лічильник менший, ніж у КТ: скидання сталося, поки панель не бачила
            $L.Base[$n] = 0.0
            $L.Resets[$n] = $now
        }
        $L.Raw[$n] = $raw
        $L.Hr[$n] = [double]$w.hr3h
        $L.Online[$n] = [bool]$w.online
    }
    $L.Earned = [double]$d.earned
    $L.Unconfirmed = $(if ($d.balance) { [double]$d.balance.unconfirmed } else { 0.0 })
    $L.Time = $now
    Save-Stats
}

# Розподіл рахунку зараз: Coins/Work/Share по воркерах, Distributed, Undistributed, Warn
function Get-LedgerCoins($L) {
    $all = @{}
    foreach ($n in @($L.Cp.CoinsQ.Keys) + @($L.Raw.Keys)) { $all[[string]$n] = $true }
    $names = @(Get-SortedKeys $all)
    $work = @{}; $sum = 0.0
    foreach ($n in $names) {
        $base = $(if ($L.Base.ContainsKey($n)) { [double]$L.Base[$n] } elseif ($L.Cp.Counters.ContainsKey($n)) { [double]$L.Cp.Counters[$n] } else { 0.0 })
        $wk = [double]$L.Acc[$n]
        if ($L.Raw.ContainsKey($n)) { $wk += [Math]::Max(0.0, [double]$L.Raw[$n] - $base) }
        $work[$n] = $wk; $sum += $wk
    }
    $coins = @{}; $cpCoins = @{}
    foreach ($n in $names) { $cpCoins[$n] = $(if ($L.Cp.CoinsQ.ContainsKey($n)) { ConvertFrom-LedgerQ $L.Cp.CoinsQ[$n] } else { 0.0 }); $coins[$n] = $cpCoins[$n] }
    $dE = [double]$L.Earned - (ConvertFrom-LedgerQ $L.Cp.EarnedQ)
    # Залишок округлення КТ до нано-монети — не нарахування і не втрата
    if ([Math]::Abs($dE) -lt 1e-8) { $dE = 0.0 }
    $und = 0.0; $warn = @()
    if ($dE -gt 0) {
        if ($sum -gt 0) {
            foreach ($n in $names) { $coins[$n] += $dE * $work[$n] / $sum }
        } else {
            # Нараховано без нової роботи (дозрів старий блок) — за часткою розподіленого раніше
            $s2 = 0.0
            foreach ($n in $names) { $s2 += $cpCoins[$n] }
            if ($s2 -gt 0) { foreach ($n in $names) { $coins[$n] += $dE * $cpCoins[$n] / $s2 } }
            else { $und = $dE }
        }
    } elseif ($dE -lt 0 -and $L.Time) {
        $warn += 'пул показує менше нарахованого, ніж у контрольній точці — перевір гаманець на сайті пулу'
    }
    foreach ($n in Get-SortedKeys $L.Resets) { $warn += "$($n): пул скинув лічильник роботи — закрий період і передай код іншим" }
    $dist = 0.0
    foreach ($n in $names) { $dist += $coins[$n] }
    $share = @{}
    foreach ($n in $names) { $share[$n] = $(if ($dist -gt 0) { $coins[$n] / $dist } else { 0.0 }) }
    @{ Names = $names; Coins = $coins; Work = $work; Share = $share; Distributed = $dist; Undistributed = $und; Warn = $warn }
}

# ---- Власники і видачі -------------------------------------------------
function Get-WorkerOwner([string]$name) {
    $o = [string]$Settings.WorkerOwners[$name]
    if ($o) { return $o }
    if (@($script:Coins | ForEach-Object { Get-LocalWorkerName $_ }) -contains $name) { return 'Я' }
    'без власника'
}
function Set-WorkerOwner([string]$name, [string]$owner) {
    if (-not ($Settings.WorkerOwners -is [hashtable])) { $Settings.WorkerOwners = @{} }
    if ($owner) { $Settings.WorkerOwners[$name] = $owner } else { $Settings.WorkerOwners.Remove($name) }
    Save-Settings
}
function Get-OwnerNames {
    $o = @('Я') + @($Settings.WorkerOwners.Values) + @($script:Stats.payouts | ForEach-Object { [string]$_.Owner })
    @($o | Where-Object { $_ } | Sort-Object -Unique)
}
function Add-LedgerPayout([string]$owner, [string]$ticker, [double]$coins, [string]$note) {
    $script:Stats.payouts = @($script:Stats.payouts) + @(@{ Id = [guid]::NewGuid().ToString('N'); Time = (Get-Date).ToString('o')
                                                          Owner = $owner; Ticker = $ticker; CoinsQ = (ConvertTo-LedgerQ $coins); Note = $note })
    Save-Stats
}

# Власник → тікер → @{ Mined; Paid }
function Get-OwnerTotals {
    $t = @{}
    foreach ($key in Get-SortedKeys $script:Stats.ledger) {
        $L = $script:Stats.ledger[$key]
        $r = Get-LedgerCoins $L
        foreach ($n in $r.Names) {
            $o = Get-WorkerOwner $n
            if (-not $t[$o]) { $t[$o] = @{} }
            if (-not $t[$o][$L.Ticker]) { $t[$o][$L.Ticker] = @{ Mined = 0.0; Paid = 0.0 } }
            $t[$o][$L.Ticker].Mined += $r.Coins[$n]
        }
    }
    foreach ($p in @($script:Stats.payouts)) {
        if (-not $p) { continue }
        $o = [string]$p.Owner
        if (-not $t[$o]) { $t[$o] = @{} }
        if (-not $t[$o][[string]$p.Ticker]) { $t[$o][[string]$p.Ticker] = @{ Mined = 0.0; Paid = 0.0 } }
        $t[$o][[string]$p.Ticker].Paid += $(if ($null -ne $p.CoinsQ) { ConvertFrom-LedgerQ $p.CoinsQ } else { [double]$p.Coins })
    }
    $t
}

# ---- Контрольна точка і обмін кодом -------------------------------------
# Закрити період для всіх рахунків: розподілене стає новою КТ, лічильники — від поточних значень пулу
function Close-LedgerPeriod {
    $now = (Get-Date).ToString('o')
    foreach ($key in Get-SortedKeys $script:Stats.ledger) {
        $L = $script:Stats.ledger[$key]
        $r = Get-LedgerCoins $L
        $q = @{}
        foreach ($n in $r.Names) { $q[$n] = ConvertTo-LedgerQ $r.Coins[$n] }
        $L.Cp = @{ Time = $now; EarnedQ = ConvertTo-LedgerQ ([double]$L.Earned - $r.Undistributed); Counters = ConvertTo-LedgerCounters $L.Raw; CoinsQ = $q }
        $L.Base = @{}
        foreach ($n in @($L.Cp.Counters.Keys)) { $L.Base[$n] = [double]$L.Cp.Counters[$n] }
        $L.Acc = @{}; $L.Resets = @{}
    }
    Save-Stats
}

function Export-LedgerCode {
    $acc = @{}
    foreach ($key in Get-SortedKeys $script:Stats.ledger) {
        $L = $script:Stats.ledger[$key]
        $acc[$key] = @{ Ticker = $L.Ticker; Pool = $L.Pool; Wallet = $L.Wallet; Exact = $L.Exact; Cp = $L.Cp }
    }
    $p = @{ v = 2; time = (Get-Date).ToString('o'); acc = $acc; owners = $Settings.WorkerOwners; payouts = @($script:Stats.payouts) }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($p | ConvertTo-Json -Depth 8 -Compress))
    $ms = New-Object IO.MemoryStream
    $gz = New-Object IO.Compression.GZipStream($ms, [IO.Compression.CompressionMode]::Compress)
    $gz.Write($bytes, 0, $bytes.Length); $gz.Close()
    $LedgerCodePrefix + [Convert]::ToBase64String($ms.ToArray())
}

# Повертає текст підсумку; кидає виняток, якщо код пошкоджений
function Import-LedgerCode([string]$code) {
    $code = ($code -replace '\s', '')
    if (-not $code.StartsWith($LedgerCodePrefix)) { throw 'це не код контрольної точки (має починатися з MPK1:)' }
    try { [byte[]]$bytes = [Convert]::FromBase64String($code.Substring($LedgerCodePrefix.Length)) } catch { throw 'код пошкоджений (скопіюй його повністю)' }
    $ms = New-Object IO.MemoryStream(, $bytes)
    $gz = New-Object IO.Compression.GZipStream($ms, [IO.Compression.CompressionMode]::Decompress)
    $sr = New-Object IO.StreamReader($gz, [Text.Encoding]::UTF8)
    $p = ConvertTo-Hash ($sr.ReadToEnd() | ConvertFrom-Json)
    $sr.Close()
    # v1 — КТ дробовими числами (перша версія), v2 — цілими
    if ([int]$p.v -notin 1, 2 -or -not ($p.acc -is [hashtable])) { throw 'невідома версія коду (онови панель)' }
    $new = 0; $upd = 0; $old = 0
    foreach ($key in Get-SortedKeys $p.acc) {
        $a = $p.acc[$key]
        $cp = $a.Cp
        if (-not ($cp -is [hashtable])) { continue }
        Repair-LedgerCp $cp | Out-Null
        $L = $script:Stats.ledger[$key]
        if (-not $L) {
            $L = New-LedgerAccount ([string]$a.Ticker) ([string]$a.Pool) ([string]$a.Wallet) ([bool]$a.Exact)
            $script:Stats.ledger[$key] = $L; $new++
        } elseif ([datetime]::Parse([string]$cp.Time) -le [datetime]::Parse([string]$L.Cp.Time)) { $old++; continue }
        else { $upd++ }
        $L.Cp = $cp
        $L.Base = @{}
        foreach ($n in @($cp.Counters.Keys)) { $L.Base[$n] = [double]$cp.Counters[$n] }
        $L.Acc = @{}; $L.Resets = @{}
    }
    if ($p.owners -is [hashtable]) { foreach ($n in @($p.owners.Keys)) { $Settings.WorkerOwners[$n] = [string]$p.owners[$n] } }
    $ids = @{}
    foreach ($x in @($script:Stats.payouts)) { if ($x) { $ids[[string]$x.Id] = $true } }
    $np = 0
    foreach ($x in @($p.payouts)) {
        if ($x -and -not $ids[[string]$x.Id]) { $script:Stats.payouts = @($script:Stats.payouts) + @($x); $np++ }
    }
    Save-Stats; Save-Settings
    $msg = "Імпортовано: нових рахунків $new, оновлено $upd, видач $np."
    if ($old) { $msg += " Пропущено $old (у тебе контрольна точка новіша або та сама)." }
    $msg
}

# ---- Опитування інших рахунків (не поточної монети) ----------------------
# Відстежуються монети з гаманцем на пулі, що надає воркерів, якщо вже є журнал
# або монету зараз майнить цей ПК чи риг HiveOS. Поточну монету опитує Update-Pool.
function Get-LedgerCoinsToFetch {
    $cur = Get-CurrentCoin
    $curKey = Get-PoolLedgerKey $cur
    $seen = @{ $curKey = $true }
    foreach ($c in @($script:Coins)) {
        if (-not $c.wallet -or [string]$c.pool.type -eq 'generic' -or -not $PoolAdapters[[string]$c.pool.type]) { continue }
        $key = Get-PoolLedgerKey $c
        if ($seen[$key]) { continue }
        $seen[$key] = $true
        $hive = $false
        if ($script:Hive) {
            foreach ($w in $script:Hive.Workers) {
                $hc = Get-HiveCoin $w
                if ($w.online -and $hc -and (Get-PoolLedgerKey $hc) -eq $key) { $hive = $true }
            }
        }
        if ($script:Stats.ledger[$key] -or $c.id -eq $script:RunningCoinId -or $hive) { $c }
    }
}

function Update-Ledger {
    if ($script:LedgerJob -and $script:LedgerJob.State -in 'Completed', 'Failed', 'Stopped') {
        $d = Receive-Job $script:LedgerJob -ErrorAction SilentlyContinue | Select-Object -Last 1
        Remove-Job $script:LedgerJob -Force
        $script:LedgerJob = $null
        $script:LedgerNext = (Get-Date).AddSeconds(20)
        $c = $script:Coins | Where-Object { $_.id -eq $d.coinId } | Select-Object -First 1
        if ($d -and $c) {
            if ($d.error) { $script:LedgerError = "$($c.name): $($d.error)" }
            else { $script:LedgerError = $null; Add-PoolLedger $c $d }
        }
    }
    if ($script:LedgerJob -or (Get-Date) -lt $script:LedgerNext) { return }
    $script:LedgerNext = (Get-Date).AddSeconds(60)
    $due = $null; $dueTime = [datetime]::MaxValue
    foreach ($c in @(Get-LedgerCoinsToFetch)) {
        $L = $script:Stats.ledger[(Get-PoolLedgerKey $c)]
        $t = $(if ($L -and $L.Time) { [datetime]::Parse([string]$L.Time) } else { [datetime]::MinValue })
        if (((Get-Date) - $t).TotalMinutes -ge $LedgerRefreshMin -and $t -lt $dueTime) { $due = $c; $dueTime = $t }
    }
    if ($due) { $script:LedgerJob = Start-PoolJob $due }
}
