$ErrorActionPreference = 'Stop'
$state = 'E:\Jatin-Project\DHAN\1\paper_state\staged_scheduler_live_20260819'
function Show-ColumnFrequency([object[]]$Rows, [string]$Column, [int]$Top = 12) {
    if (-not $Rows -or -not ($Rows[0].PSObject.Properties.Name -contains $Column)) { return }
    Write-Output ('column=' + $Column)
    $Rows | Group-Object -Property $Column | Sort-Object Count -Descending | Select-Object -First $Top Count, Name | Format-Table -AutoSize | Out-String | Write-Output
}
$candidatePath = Join-Path $state 'candidates_log.csv'
$diagnosticPath = Join-Path $state 'candidate_diagnostics.csv'
$skipPath = Join-Path $state 'skipped.csv'
$eventsPath = Join-Path $state 'research_events.csv'
$tradePath = Join-Path $state 'trades.csv'
$candidates = @(Import-Csv $candidatePath)
$diagnostics = @(Import-Csv $diagnosticPath)
$skipped = @(Import-Csv $skipPath)
$events = @(Import-Csv $eventsPath)
$trades = @(Import-Csv $tradePath)
Write-Output ('candidate_rows=' + $candidates.Count)
Write-Output ('diagnostic_rows=' + $diagnostics.Count)
Write-Output ('skipped_rows=' + $skipped.Count)
Write-Output ('research_event_rows=' + $events.Count)
Write-Output ('trade_rows=' + $trades.Count)
Write-Output '--- candidate diagnostics ---'
foreach ($col in @('decision','grade','eligible','cost_model_valid','canonical_promotion_allowed','iv_context_status','parameter_profile','reasons')) { Show-ColumnFrequency $candidates $col 10 }
Write-Output '--- split veto reasons ---'
$reasonCounts = @{}
foreach ($row in $candidates) {
    foreach ($reason in ([string]$row.reasons -split ';')) {
        $key = $reason.Trim()
        if ($key) { $reasonCounts[$key] = 1 + [int]($reasonCounts[$key]) }
    }
}
$reasonCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 20 @{Name='Count';Expression={$_.Value}}, @{Name='Reason';Expression={$_.Key}} | Format-Table -AutoSize | Out-String | Write-Output
Write-Output '--- skip records ---'
foreach ($col in @('reason','status','decision','underlying','source')) { Show-ColumnFrequency $skipped $col 15 }
Write-Output '--- selected numeric gate-related ranges ---'
foreach ($col in @('final_confidence','trade_quality','convexity_edge','regime_fit','execution_quality','side_direction_score','premium_elasticity','exp_req_ratio','contract_quality_score','gate_min_5depth_lots_each_side')) {
    if ($candidates -and ($candidates[0].PSObject.Properties.Name -contains $col)) {
        $values = @($candidates | ForEach-Object { $v = 0.0; if ([double]::TryParse(([string]$_.$col), [ref]$v)) { $v } })
        if ($values.Count -gt 0) { Write-Output ($col + '=min:' + (($values | Measure-Object -Minimum).Minimum) + ' avg:' + (($values | Measure-Object -Average).Average) + ' max:' + (($values | Measure-Object -Maximum).Maximum)) }
    }
}
Write-Output '--- recent representative candidates ---'
$candidates | Select-Object -Last 2 ts,underlying,grade,comparable_score,threshold,eligible,decision,cost_model_valid,iv_context_status | Format-Table -AutoSize | Out-String | Write-Output
