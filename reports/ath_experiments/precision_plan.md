# ATH Precision Plan

## Was wir jetzt sicher wissen
- Analysierte Runs: 15590 across run_groups=legacy_500_seed1337, legacy_500_seed1337_retry2, legacy_500_seed1337_retry3, legacy_5000_seed2026, legacy_5000_seed2026_retry2, pp10k_2026, pp10k_2027, pp10k_2028, pp10k_2029, pp10k_2030
- Hard-cap Treffer: 1513; max_dim_warn Hits: 3839
- Baseline ATH-Error-Rate: 0.1148
- Robuste Aussagen basieren auf Fehlerklassen und Modus-/Schwellenmustern, nicht auf Einzelparametern.

## Was wir vermuten (mit Confidence + Verification Plan)
- GCurve=superformula and Throat.Profile=OS-SE: rate=0.5042, consistent_multi_group=True, confidence=high.
- Coverage.Angle > 75 and Throat.Profile=OS-SE: rate=0.6205, consistent_multi_group=True, confidence=high.
- Length > 1000 mm: rate=0.2363, consistent_multi_group=True, confidence=high.
- observed final width/height/length > 2000 mm: rate=0.3941, consistent_multi_group=True, confidence=high.

## Naechste 5 Gegenproben
1. Base: OS-SE + superformula konservativ; vary nur `Coverage.Angle` in 5 deg Schritten (40..95). Expected signal: Fehleranstieg ab Schwelle. Success criterion: monotones Risiko-Delta.
2. Base: OS-SE fixed; vary nur `GCurve.Type` no_gcurve/superellipse/superformula. Expected signal: superformula bleibt riskanter. Success criterion: stabile Rangfolge ueber >=3 seeds.
3. Base: no_gcurve + OS-SE; vary nur `Length` (300..1400). Expected signal: final dimensions + hard_cap steigen mit Length. Success criterion: klarer Threshold-Bereich.
4. Base: superformula + OS-SE fixed; vary nur `GCurve.Width` (200..900). Expected signal: diameter_over_100m Cluster im oberen Bereich. Success criterion: reproduzierbare Fehlerzone.
5. Base: superformula + OS-SE fixed; vary nur `GCurve.Dist` (50..900). Expected signal: Interaktion mit Width, keine Einzelfaktor-Behauptung. Success criterion: 2D-Risikokarte Width x Dist.

## Neue/zu ergaenzende Regeln
- warn_large_observed_dimensions (warn): observed max dimension > 2000 mm.
- warn_superformula_osse_combo (warn): GCurve superformula + OS-SE.
- warn_coverage_angle_osse_high (warn): Coverage.Angle > 75 bei OS-SE.
- warn_length_over_1000 (warn): Length > 1000 mm als Risikoindikator.
- fatal_rollback_not_supported (fatal): Rollback gesetzt -> blocken (ATH inkompatibel).

## Anti-Spurious Guardrails
- Aussagen sind klassenbasiert (hard_cap_exceeded, diameter_over_100m, ...).
- Kausale Claims nur nach Gegenprobe mit Ein-Parameter-Variation.
- Interaktionen nur als Kandidaten markieren, bis ueber mehrere Seeds reproduziert.
