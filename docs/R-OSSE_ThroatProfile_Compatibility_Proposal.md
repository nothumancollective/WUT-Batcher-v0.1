# R-OSSE als Throat-Profile Option: Vorschlag fuer Kompatibilitaetslogik (2026-02-11)

Status: Analyse + Vorschlag, keine Code-Aenderung in diesem Schritt.

## Ziel

`R-OSSE` soll in der UI als dritte Option im Bereich **Throat Profile** verfuegbar sein:
- `OS-SE`
- `R-OSSE`
- `Circular Arc`

Die R-OSSE-Parameter
- `R`, `r0`, `a0`, `a`, `k`, `r`, `m`, `b`, `q`
sollen **nur dann verfuegbar** sein, wenn `R-OSSE` gewaehlt ist.

## Evidenz aus den gelieferten Quellen

### 1) Funktionierende Referenz-CFG (V50)
Datei:
- `C:\Users\maximilianheinze\Desktop\WaveguideDesignsErsteIterationsrunde\cfg\WUT_KoaxInsertWG_V50.cfg`

Beobachtung:
- Nutzt `R-OSSE = { ... }` Block mit genau den 9 Parametern.
- Kommentar im Header: `R-OSSE profile (ersetzt OS-SE + Rollback)`.
- Kein `Throat.Profile` fuer diesen Fall gesetzt.

Fachliche Schlussfolgerung:
- In der praktischen, funktionierenden CFG ist `R-OSSE` ein eigener Geometriemodus mit eigenem Parameterblock.

### 2) R-OSSE Waveguide rev7
Datei:
- `C:\Users\maximilianheinze\Desktop\R-OSSE Waveguide rev7.pdf`

Relevante Inhalte:
- Parameter-Tabelle listet exakt: `R, a, r0, a0, k, r, m, b, q`.
- Bedeutungen:
  - `a` = nominal coverage angle (*0.5)
  - `a0` = throat opening angle (*0.5)
  - `R` = outer radius
- Enthaltenes ATH-Skriptbeispiel zeigt `R-OSSE = { ... }` direkt als CFG-Block.

Fachliche Schlussfolgerung:
- Die 9 Parameter sind der normative Kern von R-OSSE.
- `a` und `a0` sind Halbwinkel (wichtig fuer UI-Hinweise).

### 3) ATH - Segmentizing a horn
Datei:
- `C:\Users\maximilianheinze\Desktop\ATH - Segmentizing a horn.pdf`

Relevanter Punkt:
- Segmentierungsbeispiel basiert explizit auf einer freien, axisymmetrischen `R-OSSE`-Grundform.

Fachliche Schlussfolgerung:
- R-OSSE wird als eigenstaendiges Ausgangsprofil behandelt, nicht als Unterfall von `OS-SE`/`Circular Arc`.

## Ist-Zustand im Projekt

- `Throat.Profile` im Katalog: aktuell nur `1` (OS-SE) und `3` (Circular Arc).
- `R-OSSE` existiert bereits als `object`-Key im Katalog (`app/knowledge/ath/catalog.v1.json`).
- Ruleset enthaelt bereits Warnlogik fuer Mischbetrieb (`validity_rosse_block_exclusive`).

Gap:
- Es gibt noch keine saubere, benutzergefuehrte Koppelung:
  - Auswahl im Throat-Profil
  - Sichtbarkeit der 9 R-OSSE-Parameter
  - konsistente Block-Validierung

## Vorschlag: Modellierung und Regeln

## 1) UI-/Datenmodell fuer Throat-Profile

Empfehlung (kompatibel mit bestehender Logik, ohne neue ATH-Keys):
- Im UI-Dropdown „Throat Profile“ drei Optionen anzeigen:
  - `OS-SE`
  - `R-OSSE`
  - `Circular Arc`

Interne Persistenz:
- `OS-SE`:
  - `Throat.Profile = 1`
  - `R-OSSE` entfernen/nicht setzen
- `Circular Arc`:
  - `Throat.Profile = 3`
  - `R-OSSE` entfernen/nicht setzen
- `R-OSSE`:
  - `Throat.Profile` nicht setzen
  - `R-OSSE = {...}` setzen

Begruendung:
- Kein neuer ATH-Key notwendig.
- Keine neue, nicht dokumentierte `Throat.Profile`-Wertkodierung.
- Entspricht direkt funktionierender V50-CFG.

## 2) Sichtbarkeitslogik (Kompatibilitaet)

Wenn `isDefined(R-OSSE)`:
- R-OSSE-Unterparameter-Editor anzeigen (`R,r0,a0,a,k,r,m,b,q`).
- OS-SE/CircArc-abh. Felder ausblenden:
  - `Term.s`, `Term.n`, `Term.q`, `OS.k`
  - `CircArc.TermAngle`, `CircArc.Radius`
- Rollback-Detailfelder ausblenden:
  - `Rollback`, `Rollback.StartAt`, `Rollback.Angle`, `Rollback.Exp`

Wenn `Throat.Profile == 1` oder `Throat.Profile == 3`:
- `R-OSSE`-Editor ausblenden.

Hinweis:
- Morph/Mesh koennen weiterhin sichtbar bleiben; V50 zeigt diese Kombination als praktisch nutzbar.

## 3) Validitaetslogik fuer R-OSSE

Regelvorschlag (fatal):
- Bei `isDefined(R-OSSE)` muessen alle 9 Felder vorhanden sein:
  - `get(R-OSSE,'R')`, `get(R-OSSE,'r0')`, `get(R-OSSE,'a0')`, `get(R-OSSE,'a')`,
  - `get(R-OSSE,'k')`, `get(R-OSSE,'r')`, `get(R-OSSE,'m')`, `get(R-OSSE,'b')`, `get(R-OSSE,'q')`

Regelvorschlag (warn):
- Mischbetrieb mit klassischen Profilfeldern:
  - `isDefined(R-OSSE)` und gleichzeitig `isDefined(Throat.Profile)` oder `isDefined(Term.*)` oder `isDefined(CircArc.*)` oder `isDefined(Rollback*)`

Begruendung:
- R-OSSE-Formel ist ein vollstaendiger Profilmodus.
- Mischbetrieb ist laut bisheriger Wissensbasis nicht sauber spezifiziert.

## 4) Sweepability-Vorschlag

Phase A (minimal risikoarm):
- R-OSSE-Block als Ganzes nicht sweepbar (nur fixe Constraints), bis Objektfeld-Sweeps sauber modelliert sind.

Phase B (spaeter):
- gezielte Sweeps auf Mitgliedsebene (`R`, `a`, `k`, etc.) via strukturierter Objekt-UI.

## 5) User-Hinweise/Placeholder fuer R-OSSE

Empfohlene Kurztexte:
- `a0`: `Throat-Halbwinkel [deg]`
- `a`: `Coverage-Halbwinkel [deg]`
- `R`: `Aussenradius [mm]`
- `r0`: `Throat-Radius [mm]`

Optionaler Startwert-Hinweis aus Rev7-Beispiel:
- `R=130, r0=12.7, a0=7.5, a=39, k=1.8, r=0.3, m=0.8, b=0.3, q=3.7`

## 6) Akzeptanzkriterien fuer die spaetere Implementierung

1. Im Throat-Profile-Dropdown sind genau 3 Modi sichtbar.
2. Bei `R-OSSE` sind nur die 9 R-OSSE-Parameter (plus allgemeine kompatible Gruppen wie Morph/Mesh) sichtbar.
3. Bei `OS-SE`/`Circular Arc` sind R-OSSE-Parameter nicht sichtbar.
4. Eine V50-aehnliche Konfiguration laesst sich ohne Workaround eingeben und validieren.
5. Keine doppeldeutige CFG-Ausgabe:
   - R-OSSE-Modus schreibt den `R-OSSE={...}` Block.
   - Keine widerspruechlichen Profileingaben parallel.

## Offene Punkte (vor Implementierung klaeren)

1. Soll `Rollback` in R-OSSE strikt verboten (`fatal`) oder zunaechst `warn` sein?
2. Sollen R-OSSE-Parameter in der ersten Iteration sweepbar sein oder nur fix?
3. Soll die UI in R-OSSE-Modus `Throat.Profile` intern komplett entfernen (empfohlen), um Konflikte robust zu vermeiden?
