# Batch Analyzer KPI Research — RAW (Verbatim)

**Source file:** `Batch Analyser KPI Research.md`  
**Imported into repo docs:** 2026-02-21  
**SHA256 (first 12):** `e26cb5d9f9ad`

> Everything below this line is a verbatim copy of the source research.  
> Do not edit the raw section; add comments/structure in `01_kpi_foundations.md`.

---

# KPI-basierter Analyzer für MT/HT-Hörner aus komplexen Polardaten

## Entwicklungsphasen für MT/HT-Hörner

Die Mess- und Bewertungslogik sollte die physikalischen Zwänge von Hörnern/Waveguides widerspiegeln: Hörner erfüllen (mindestens) zwei Hauptfunktionen – **Treiber-Loading/Effizienz** und **Direktivitätskontrolle** – und moderne MT/HT-Entwicklung verschiebt den Fokus oft deutlich in Richtung Direktivität (teils auf Kosten eines „sauberen“ Loads). citeturn18view0turn16view1 Für die Analyzer-Architektur ist deshalb entscheidend, **welche Kennzahlen in welcher Phase** tatsächlich „entwicklungsgerecht“ sind.

### Konzept-Exploration

**Primäre akustische Ziele**  
In dieser Phase geht es um die grobe Festlegung von Topologie/Skalierung: Mundabmessungen, Seitenverhältnis, Grundkontur (z. B. conical/OS-artig, Diffraction-Ansätze), Zielabdeckung H/V, sowie die Frage, **bis zu welcher unteren Frequenz** die beabsichtigte Abdeckung überhaupt kontrollierbar ist. Der Zusammenhang zwischen Abdeckwinkel, Munddimension und Frequenz der „Loss of Directivity Control“ ist für Hörner fundamental. citeturn6view0

**Relevante messbare Eigenschaften (polar-basiert)**  
Die großen, robusten Mustermerkmale: grober Abdeckwinkel (z. B. -6 dB „coverage“), Beginn der Aufweitung unterhalb der Direktivitätskontrolle, offensichtliche Asymmetrien zwischen H/V sowie grobe Nebenkeulen/„Spill“ außerhalb der Zielabdeckung. citeturn6view0turn5view0

**Irrelevant/irreführend in dieser Phase**  
Feinskalige Ripple- oder „Smoothness“-Metriken über Frequenz sind oft **simulations- und mesh-sensitiv** und können Frühentscheidungen verzerren. Ebenso sind phasenbasierte Kennzahlen (GD/Phase-Linearity) meist noch nicht stabil interpretierbar, solange Geometrie/Skalierung nicht plausibel ist.

### Direktivitäts-Shaping

**Primäre akustische Ziele**  
Ab hier wird die Abstrahlform gezielt geformt (z. B. 90°×40°) und die H/V-Charakteristik in Richtung Ziel gebracht. „Constant/Uniform coverage“-Konzepte sind historisch explizit als Antwort auf stark frequenzabhängige Beamwidth entstanden. citeturn6view0turn15view0

**Relevante messbare Eigenschaften**  
Beamwidth-vs-Frequenz in H/V (und zunehmend Diagonal als Plausibilitätscheck), Pattern-Form über Winkel (inkl. Nebenkeulen), sowie eine robuste Normalisierung/Referenzbildung, weil gerade Constant-Directivity-Hörner lokal auch **On-Axis-Dips** oder ein Maximum nicht exakt bei 0° zeigen können. citeturn5view0

**Irrelevant/irreführend**  
„Absolutwerte“ von DI/Q sind in dieser Phase häufig weniger belastbar, wenn DI aus unvollständigen 3D-Daten (nur H/V/D) approximiert wird oder der Referenzpunkt instabil ist. Die Richtung stimmt, aber die Zahl kann trügerisch sein, wenn die Referenz (0° vs Maximum vs power-normalized) nicht konsequent definiert ist. citeturn5view0turn2view0

### Beamwidth-Stabilisierung

**Primäre akustische Ziele**  
Die Abdeckung soll über ein Band **stabil** werden: möglichst konstante Beamwidth, kontrollierter Übergang am unteren Ende (Aufweitung unterhalb der Kontrollfrequenz) und minimierte „Jumps“/„Collapses“ im oberen Band (Beugung, Moden, Apertur-Effekte). Der typische Verlauf von Beamwidth/DI bei uniform coverage horns wird in der Literatur als Regimewechsel beschrieben (Verlust der Kontrolle unten, relativ stabile Zone, dann wieder Effekte oben). citeturn15view0turn6view0

**Relevante messbare Eigenschaften**  
Kennzahlen, die **Varianz/Gradienten** der Beamwidth erfassen, plus Nebenkeulen-/Spill-Kennzahlen (Energie außerhalb Zielabdeckung), weil diese unmittelbar Arrayability und Boundary-Interaktion beeinflussen. citeturn5view0

**Irrelevant/irreführend**  
Einzelpunkt-/Einzelfrequenzbewertungen (z. B. „Beamwidth bei 8 kHz“) sind als Filter zu fragil. Entscheidend ist die **Bandkohärenz** (über Oktaven).

### Resonanz- und Reflektionskontrolle

**Primäre akustische Ziele**  
Jetzt rücken interne Reflexionen, Mundreflexionen, Higher-Order-Modes, Diffraktionseffekte und deren akustische „Signaturen“ in den Fokus. Mundreflexionen können im Horn-Impedanzverlauf Peaks/Dips erzeugen, die sich als Ripple/Artefakte im Nutzsignal zeigen. citeturn16view1turn18view0

**Relevante messbare Eigenschaften**  
Polar-Smoothness (Winkel), Ripple-Indizes (Frequenz, off-axis), Nebenkeulenstruktur, und – wenn Phase genutzt wird – group-delay-/phase-basierte Stabilitätsmaße, wobei deren Interpretation eine saubere Phase/Unwrapping/Abtastrate voraussetzt. citeturn17view0turn20view0

**Irrelevant/irreführend**  
In dieser Phase ist eine reine „Beamwidth-OK“-Aussage nicht ausreichend: ein Horn kann die Zielbeamwidth treffen und trotzdem stark „unsauber“ sein (Welligkeit, HOM, Splatter-Lobes).

### Finale Optimierung

**Primäre akustische Ziele**  
Feintuning für Robustheit (Parameterstreuungen, kleine Geometrieänderungen), saubere Übergänge/„polite“ Polars, konsistente Directivity- und Zeit-/Phasencharakteristik, und – je nach Produkt – Zielmetriken für EQ-/Processing-Strategien.

**Relevante messbare Eigenschaften**  
Stabile bandgemittelte KPIs, Pareto-Abwägungen (z. B. Pattern-Control-Bandbreite vs Ripple), sowie über Projekte hinweg vergleichbare Normalisierung/Referenzen.

**Irrelevant/irreführend**  
Überoptimierung auf einen „Score“ ohne Blick auf Failure-Modes (z. B. schmale Nebenkeulen) – genau diese Failure-Modes sind bei Hörnern kritisch für Praxisprobleme (Grenzflächen, Arrays). citeturn5view0

## Polarbasierte KPIs aus komplexen H/V/D-Daten

### Grundlegende Datenrepräsentation und Vorverarbeitung

**Notation**  
Für jede Ebene \(p \in \{H,V,D\}\) liege eine komplexe Übertragungsfunktion (oder komplexer Schalldruck) \(P_p(f_k,\theta_i)\) vor, gespeichert als Re/Im pro Frequenzbin \(f_k\) und Winkelbin \(\theta_i\). Daraus:

- Betrag: \(A_p(f,\theta)=|P_p(f,\theta)|\)  
- Pegel (relativ): \(L_p(f,\theta)=20\log_{10}(A_p(f,\theta))\)  
- Phase: \(\varphi_p(f,\theta)=\arg(P_p(f,\theta))\)

**Wichtige Robustheitsdetails, die KPIs direkt beeinflussen**  
- **Referenz/Normalisierung**: Coverage-/Beamwidth-Berechnungen können fehlschlagen, wenn On-Axis kein Maximum ist (typisch bei manchen CD-Hörnern in Teilbereichen). Eine robustere Referenz ist z. B. das Winkelmaximum bzw. power-normalisierte Iteration über die Coverage-Region. citeturn5view0  
- **„First“- vs „Last“-Crossing** bei -6 dB: Bei Nebenkeulen kann die erste -6 dB-Unterschreitung zu optimistischen Beamwidth-Angaben führen; die letzte -6 dB-Unterschreitung ist für „keine Energie außerhalb“ oft relevanter. citeturn5view0  
- **Auflösung**: Unzureichende Winkelauflösung kann Interpolationsfehler erzeugen, wenn die Richtcharakteristik komplex genug ist. citeturn2view0

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["horn loudspeaker polar response contour plot","constant directivity horn beamwidth vs frequency plot","waveguide polar map heatmap SPL angle frequency"],"num_per_query":1}

### KPI-Set aus Polars (10 Stück, rein aus \(f\times\theta\) und H/V/D)

Im Folgenden sind KPIs so definiert, dass sie **direkt aus eurer Matrixstruktur** berechenbar sind. Jede KPI enthält: Mathematik, Berechnungsschritte, Interpretation für MT/HT-Hörner, Phasenbezug, Stabilität für Batch-Ranking, Sensitivität.

#### KPI „Beamwidth-Kurve“ \(BW_p(f)\) mit robuster -6 dB-Definition

**Mathematische Definition**  
Beamwidth wird in der Praxis häufig als eingeschlossener Winkel zwischen den -6 dB-Punkten relativ zu einer Referenz definiert. citeturn5view0turn4search28  
Für eure Daten (typisch \(\theta\in[0,90^\circ]\), symmetrisch angenommen) definieren wir zunächst eine Normalisierung:
\[
L^{(ref)}_p(f,\theta)=L_p(f,\theta)-L_p(f,\theta_{ref}(f))
\]
mit \(\theta_{ref}(f)\) nach gewählter Referenzstrategie.

Robuste „Last-Crossing“-Halbwinkeldefinition:
\[
\theta_{6,p}(f)=\min\{\theta: \forall\theta' \ge \theta,\; L^{(ref)}_p(f,\theta') \le -6\,\text{dB}\}
\]
Dann:
\[
BW_p(f)=2\theta_{6,p}(f)
\]

**Berechnung aus \(f\times\theta\)-Matrix**  
1) Wähle \(\theta_{ref}(f)\):  
- „On-axis“: \(\theta_{ref}=0^\circ\) (schnell, aber fehleranfällig bei On-Axis-Dip). citeturn5view0  
- „Local maximum“: \(\theta_{ref}=\arg\max_{\theta\le \theta_{maxref}} L_p(f,\theta)\) mit z. B. \(\theta_{maxref}=10^\circ\) als Plausibilitätscheck. citeturn5view0  
- „Power-normalized“ (empfohlen für Ranking): Iterative Normalisierung auf 0 dB Durchschnittsleistung innerhalb der Coverage und Rückrechnen der Coverage, bis Konvergenz (EAW beschreibt genau diese Iterationsidee). citeturn5view0  

2) Bestimme \(\theta_{6,p}(f)\) diskret (und optional linear interpoliert zwischen Bins).

**„Gut“ vs „schlecht“ für MT/HT-Hörner**  
- **Gut**: \(BW_p(f)\) nahe Ziel (z. B. 90°/40°) und über Band relativ konstant. Verlust der Kontrolle nach unten ist erwartbar, sollte aber „glatt“ einsetzen. citeturn6view0turn15view0  
- **Schlecht**: starke Einbrüche (plötzliche Engstellung) oder Sprünge (plötzliche Aufweitung), häufig Hinweis auf Diffraktion/Moden/Apertur-Effekte.

**Geometrische Bedeutung**  
- Zu frühe Engstellung: Apertur zu klein relativ zu Wellenlänge, oder starke Modenführung/Kanten.  
- Sprunghafte Aufweitung: Interferenz/Reflexionen, „pattern flip“, starke Nebenkeulen.

**Nützlichste Phase**: Konzept → Beamwidth-Stabilisierung. citeturn6view0turn15view0  
**Batch-Ranking-Stabilität**: hoch, wenn Referenzstrategie konsistent und Winkelauflösung ausreichend. citeturn2view0turn5view0  
**Sensitivität**: mittel; empfindlich auf Winkelauflösung und „On-axis dip“/Nebenkeulen (deshalb Last-Crossing + robuste Referenz). citeturn2view0turn5view0

#### KPI „Beamwidth-Fehler gegen Ziel“ \(E_{BW}\)

**Definition**  
Für Zielbeamwidth \(BW^{tar}_p(f)\) (konstant oder frequenzabhängig):
\[
E_{BW,p} = \sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)\left(BW_p(f)-BW^{tar}_p(f)\right)^2}{\sum_{f\in\mathcal{B}} w(f)}}
\]
mit Band \(\mathcal{B}\) (z. B. 1–10 kHz) und Gewichtung \(w(f)\) (empfohlen: gleich pro Oktave, also \(w(f)\propto 1/f\)).

**Berechnung**  
- Verwende \(BW_p(f)\) aus obiger KPI.  
- Bandwahl typisch getrennt für MT- und HF-Hörner (z. B. MT: 500 Hz–4 kHz, HF: 1 kHz–16 kHz).

**Gut/schlecht**  
- **Gut**: RMS-Fehler wenige Grad (z. B. ≤5°) über das relevante Band → treffsicheres Shaping.  
- **Schlecht**: großer RMS → Zielabdeckung nicht erreicht; Geometrie (Mund/Aspekt/Flare) falsch skaliert.

**Phase**: Direktivitäts-Shaping/Beamwidth-Stabilisierung.  
**Ranking-Stabilität**: hoch (skalare KPI, robust).  
**Sensitivität**: hängt direkt an Beamwidth-Stabilität; daher gleiche Abtastraster wichtig. citeturn2view0

#### KPI „Pattern-Control-Bandbreite“ \(B_{PC}\)

**Definition**  
Gesucht ist der größte zusammenhängende Frequenzbereich, in dem die Beamwidth innerhalb einer Toleranz liegt:
\[
\mathcal{F}_{ok}=\{f\in \mathcal{B}: |BW_p(f)-BW^{tar}_p(f)| \le \Delta BW\}
\]
Dann z. B. als Bandbreite in Oktaven:
\[
B_{PC,p}=\log_2\left(\frac{f_{high}}{f_{low}}\right)
\]
wobei \(f_{low},f_{high}\) die Grenzen des größten zusammenhängenden Intervalls in \(\mathcal{F}_{ok}\) sind.

**Interpretation**  
- Direktivitätskontrolle bricht nach unten weg; der Zusammenhang Mundgröße–Coverage–Kontrollfrequenz ist klassisch: für eine feste Abdeckung muss die Munddimension wachsen, um Kontrolle tiefer zu halten. citeturn6view0  
- In einem idealen uniform coverage horn wäre die Beamwidth oberhalb der Kontrollfrequenz relativ konstant (in Realität mit Abweichungen). citeturn6view0turn15view0

**Gut/schlecht**  
- **Gut**: große \(B_{PC}\) (viele Oktaven) mit moderater Toleranz (±5° oder ±10°).  
- **Schlecht**: kurzer Bereich → Horn „trifft“ Abdeckung nur punktuell.

**Phase**: Konzept → Stabilisierung.  
**Ranking-Stabilität**: sehr hoch (scalar + bandbasiert).  
**Sensitivität**: moderat; benötigt ausreichend Frequenzauflösung um bandgrenzen sauber zu schätzen.

#### KPI „Beamwidth-Glätte“ \(S_{BW}\) und „Jump/Collapse“-Detektoren

**Definition (Glätte)**  
Auf Log-Frequenz-Achse (Oktaven) ist ein sinnvoller Glättemaßstab:
\[
S_{BW,p} = \sqrt{\frac{1}{|\mathcal{B}|}\sum_{f\in\mathcal{B}}\left(\frac{d\,BW_p}{d\,\log_2 f}\right)^2}
\]

**Jump/Collapse Flags**  
Diskrete Ableitung pro Oktave:
\[
\Delta BW_p(f)=BW_p(2f)-BW_p(f)
\]
- **Collapse** wenn \(\Delta BW_p(f) < -\tau_c\) (z. B. \(-15^\circ\)/Oktave)  
- **Jump** wenn \(\Delta BW_p(f) > \tau_j\) (z. B. \(+15^\circ\)/Oktave)

**Berechnung**  
- Ableitungen numerisch auf log-spaced Frequenzgrid oder resampling eurer variable bins auf ein internes Standardgrid (empfohlen für Vergleichbarkeit).  
- Für Jump/Collapse: zusätzlich Mindestpersistenz (z. B. 2–3 Bins), sonst „Noise“.

**Gut/schlecht & geometrische Bedeutung**  
- **Gut**: geringe Glättekennzahl und keine starken Flags.  
- **Schlecht**: Flags → meist Interferenz/Reflexion, Diffraktions- oder Moden-Effekte, die für Arrays/Boundary kritisch sind. citeturn5view0turn18view0

**Phase**: Stabilisierung, teils Resonanzkontrolle.  
**Ranking-Stabilität**: hoch (wenn geglättet/robust).  
**Sensitivität**: erfordert hinreichende Frequenzauflösung; Winkelauflösung wirkt indirekt über \(BW(f)\). citeturn2view0

#### KPI „DI“ (Directivity Index) – zwei pragmatische Varianten aus H/V/D

**Warum zwei Varianten?**  
Eine „korrekte“ DI basiert auf Integration über den Raumwinkel:
\[
Q(f)=\frac{4\pi}{\int |\Gamma(f,\theta,\phi)|^2\,d\Omega},\qquad DI(f)=10\log_{10}Q(f)
\] 
citeturn2view0turn18view0  
Die Mess-/Datenstandards erwarten dafür eine 3D-Sampling-Strategie auf einer Kugel in sphärischen Koordinaten; eine einzelne Scan-Line beschreibt das System nicht vollständig. citeturn14search2turn14search27 Mit nur H/V/D ist jede „volle“ Integration eine Approximation – kann aber für Ranking innerhalb konsistenter Daten trotzdem nützlich sein.

**Variante A: Beamwidth-basierte Ersatz-DI \(DI_{BW}\)**  
Für rechteckige Abdeckung mit Halbwinkeln \(\alpha_H=\theta_{6,H}\), \(\alpha_V=\theta_{6,V}\). Approximierter Strahlraumwinkel:
\[
\Omega_{BW}\approx 4\,\sin(\alpha_H)\,\sin(\alpha_V)
\]
(heuristische Näherung; alternativ kleine-Winkel-Näherung \(\Omega\approx 4\alpha_H\alpha_V\) in rad). Dann:
\[
Q_{BW}(f)=\frac{4\pi}{\Omega_{BW}(f)},\quad DI_{BW}(f)=10\log_{10}Q_{BW}(f)
\]

**Variante B: „Plane-Power“-DI Surrogat \(DI_{pp}\)**  
Pragmatisch integriert man pro Ebene mit \(\sin\theta\)-Gewichtung (axialsymmetrische Annahme als Surrogat):
\[
Q_{pp,p}(f)=\frac{2\,|P_p(f,0)|^2}{\int_0^\pi |P_p(f,\theta)|^2\sin\theta\,d\theta}
\]
und \(DI_{pp,p}(f)=10\log_{10}Q_{pp,p}(f)\). Die Definition von \(DI=10\log_{10}Q\) ist standard- und lehrbuchkonform; die Approximation liegt in der 3D-Annahme. citeturn2view0turn18view0

**Gut/schlecht**  
- **Gut**: monotone/„ruhige“ DI-Entwicklung ohne starke Ripple; bei uniform coverage horns ist ein typischer Verlauf beschrieben (Regimewechsel und dann relativ stabil). citeturn15view0  
- **Schlecht**: starke DI-Ripple → Nebenkeulen, Moden, Diffraktion.

**Phase**: eher Refinement → Finale Optimierung (weil DI ohne saubere Referenz/3D-Sampling sonst trügerisch). citeturn14search27turn5view0  
**Ranking-Stabilität**: mittel (A hoch, B mittel; hängt von Referenz/Abdeckung/3D-Annahme ab).  
**Sensitivität**: DI ist empfindlich gegenüber unvollständiger Raumwinkelabdeckung und Normalisierung. citeturn5view0turn14search27

#### KPI „DI-Smoothness“ \(S_{DI}\)

**Definition**  
Auf log-F-Skala:
\[
S_{DI}=\sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)\left(\frac{d\,DI}{d\,\log_2 f}\right)^2}{\sum_{f\in\mathcal{B}} w(f)}}
\]
oder als Ripple nach Entfernen einer geglätteten Trendkurve \(DI_s(f)\):
\[
S_{DI,ripple}=\sqrt{\frac{\sum w(f)(DI(f)-DI_s(f))^2}{\sum w(f)}}
\]

**Gut/schlecht**  
- **Gut**: kleine Werte → „gleichmäßige Direktivität“.  
- **Schlecht**: starke Variation → typischerweise Unsauberkeiten in Polars/Spill, mit Praxisrisiken. citeturn5view0

**Phase**: Resonanzkontrolle → Finale.  
**Ranking-Stabilität**: mittel bis hoch, wenn DI-Variante konsistent ist.  
**Sensitivität**: gleicht DI-Empfindlichkeiten; Frequenzauflösung relevant.

#### KPI „Uniformität innerhalb Coverage“ \(E_{cov}\) (RMS-Winkel-Fehler)

**Motivation & Quelle**  
EAW schlägt als figure-of-merit vor, den RMS-Fehler innerhalb der Coverage zu berechnen, um die Konsistenz im Hörbereich zu bewerten. citeturn5view0

**Definition**  
Sei \(\theta_{6,p}(f)\) euer Coverage-Halbwinkel (KPI Beamwidth). Innerhalb:
\[
E_{cov,p}(f)=\sqrt{\frac{1}{N_f}\sum_{\theta_i\le \theta_{6,p}(f)}\left(L^{(pow)}_p(f,\theta_i)-0\right)^2}
\]
wobei \(L^{(pow)}\) die power-normalisierte Darstellung ist (0 dB Mittelwert in der Coverage). citeturn5view0  
Bandgemittelt:
\[
E_{cov,p}=\sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)E_{cov,p}(f)^2}{\sum_{f\in\mathcal{B}} w(f)}}
\]

**Gut/schlecht**  
- **Gut**: geringer RMS-Fehler (wenige dB) → gleichmäßige Abdeckung.  
- **Schlecht**: hoher Fehler → „Hotspots“/Dips im Hörbereich, oft durch Interferenzen/Reflexionen.

**Geometrische Bedeutung**  
- Hohe Fehlerzahlen sind häufig Symptome von Nebenkeulenstruktur, HOM, Mundreflexionen oder abrupten Konturänderungen.

**Phase**: Stabilisierung → Resonanzkontrolle.  
**Ranking-Stabilität**: hoch, wenn Coverage robust berechnet wird.  
**Sensitivität**: abhängig von Coverage-Algorithmus und Winkelauflösung. citeturn2view0turn5view0

#### KPI „Spill-/Sidelobe-Index“ \(Q_{beam}\) bzw. „Energie außerhalb Coverage“

**Motivation & Quelle**  
EAW diskutiert, dass klassische Q-Berechnung irreführend sein kann, wenn das Maximum nicht auf Achse liegt, und schlägt eine modifizierte Kennzahl \(Q(beam)\) vor: Verhältnis von mittlerer Quadratschalldruckleistung innerhalb Coverage zur mittleren Quadratschalldruckleistung über alle Richtungen. citeturn5view0

**Pragmatische Definition (pro Ebene als Surrogat, oder kombiniert)**  
Pro Ebene:
\[
R_{spill,p}(f)=\frac{\sum_{\theta_i>\theta_{6,p}(f)} |P_p(f,\theta_i)|^2\,w_\theta(\theta_i)}
{\sum_{\theta_i\le\theta_{6,p}(f)} |P_p(f,\theta_i)|^2\,w_\theta(\theta_i)}
\]
mit Winkelgewicht \(w_\theta(\theta)\approx \sin\theta\) als 3D-Surrogat. citeturn2view0

Alternativ als „Beam sharpness“:
\[
Q_{beam,p}(f)=\frac{\text{mean}_{\theta\le\theta_{6,p}}(|P|^2)}{\text{mean}_{\text{all }\theta}(|P|^2)}
\]
analog zur EAW-Idee. citeturn5view0

**Gut/schlecht**  
- **Gut**: wenig Spill (kleines \(R_{spill}\)) bzw. hohes \(Q_{beam}\) bei gleichzeitiger guter Uniformität.  
- **Schlecht**: hohe Energie außerhalb Coverage → Boundary-Reflexionen/Array-Interferenzrisiko. citeturn5view0

**Phase**: Stabilisierung → Finale (sehr ranking-tauglich für „arrayable horns“).  
**Ranking-Stabilität**: hoch (wenn Coverage stabil).  
**Sensitivität**: mittel; Nebenkeulen sind sensitiv auf Winkelauflösung. citeturn2view0

#### KPI „H/V/D-Konsistenz“ und „Symmetrie“ \(E_{sym}\)

**Definition (Simple)**  
Vergleich H vs V Beamwidth:
\[
E_{sym,BW} = \sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)\left(BW_H(f)-BW_V(f)\right)^2}{\sum w(f)}}
\]
Zusätzlich kann D als Plausibilitätsanker genutzt werden (bei rechteckigen Hörnern ist die Diagonale oft „zwischen“ H und V, aber nicht strikt). Der Vorteil von D ist, dass viele „corner“-Effekte (Mundkanten) dort sichtbar werden.

**Definition (Form-Korrelation)**  
Normiere pro Frequenz die Kurven:
\[
\tilde{L}_p(f,\theta)=L^{(ref)}_p(f,\theta) - \text{mean}_{\theta\le \theta_{6,p}(f)}L^{(ref)}_p(f,\theta)
\]
Dann Korrelations-/Fehlermaß zwischen Ebenen, z. B.:
\[
E_{sym,shape}=\text{mean}_{f\in\mathcal{B}}\left(\sqrt{\frac{1}{N_\theta}\sum_{\theta}(\tilde{L}_H-\tilde{L}_V)^2}\right)
\]

**Gut/schlecht**  
- **Gut**: Erwartungen an das Aspektverhältnis werden erfüllt (z. B. H deutlich breiter als V bei 90×40).  
- **Schlecht**: ungewollte Annäherung oder Kreuzung → Geometrie koppelt Achsen ungewollt, oder starke nicht-separable Moden.

**Phase**: Shaping → Stabilisierung → Finale.  
**Ranking-Stabilität**: hoch (skalare Fehler).  
**Sensitivität**: moderat.

#### KPI „Polar-Smoothness“ über Winkel \(S_{\theta}\)

**Definition**  
Zur quantitativen Erfassung von Winkellobing/Ripple kann man zweite Differenzen verwenden:
\[
S_{\theta,p}(f)=\sqrt{\frac{1}{N_\theta}\sum_i \left(\Delta^2_{\theta}\,L^{(ref)}_p(f,\theta_i)\right)^2}
\]
Bandgemittelt:
\[
S_{\theta,p}=\sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)S_{\theta,p}(f)^2}{\sum w(f)}}
\]

**Interpretation**  
Hohe zweite Ableitungen deuten auf „wiggly“ Polars, Nebenkeulen, Interferenzen. Gerade bei unvollkommenen Hörnern sind Standarddefinitionen (Coverage, Q) sonst zu optimistisch; EAW motiviert genau diesen Bedarf nach zusätzlichen figures-of-merit. citeturn5view0

**Gut/schlecht**  
- **Gut**: niedrige Winkelkrümmung → „monoton fallende“ Polars.  
- **Schlecht**: hohe Krümmung → Nebenkeulen/Interferenzstruktur.

**Phase**: Resonanzkontrolle und Finale.  
**Ranking-Stabilität**: mittel bis hoch, wenn winkelgeglättet (z. B. Savitzky–Golay über \(\theta\)).  
**Sensitivität**: hoch gegenüber Winkelauflösung. citeturn2view0

#### KPI „Off-axis Ripple Index“ über Frequenz \(R_{off}\)

**Definition**  
Für ausgewählte Winkel \(\theta \in \Theta_{eval}\) (z. B. 0°, 10°, 20°, 30°, 45°, 60°) und pro Ebene:
1) Entferne Trend durch Glättung in konstanter Oktavauflösung (z. B. 1/6 Oktave): \(L_s(f,\theta)\).  
2) Ripple:
\[
R_{off,p}(\theta)=\sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)\left(L^{(ref)}_p(f,\theta)-L_{s,p}(f,\theta)\right)^2}{\sum w(f)}}
\]
Aggregiere z. B. als Mittel über Off-Axis-Winkel außer 0°:
\[
R_{off,p}=\text{mean}_{\theta\in\Theta_{eval}\setminus\{0\}} R_{off,p}(\theta)
\]

**Interpretation**  
Ripple off-axis korreliert oft mit Moden/Reflexionen (Mund/Throat) und ist für MT/HT-Hörner praxisrelevant, weil die Tonalität abseits der Achse stabil bleiben soll. Mundreflexionen und unruhige Impedanzen werden als Ursachen für Peaks/Dips diskutiert. citeturn16view1turn18view0

**Phase**: Resonanzkontrolle → Finale.  
**Ranking-Stabilität**: mittel (stark abhängig von Frequenzauflösung und Glättungskonvention).  
**Sensitivität**: hoch; verlangt konsistente Frequenzbins oder internes Resampling.

#### KPI „Group-Delay-Stabilität“ \(S_{GD}\) (nur falls Phase genutzt wird)

**Definition**  
Group delay:
\[
\tau_g(f,\theta)= -\frac{d\varphi(f,\theta)}{d\omega}
\]
citeturn17view0turn20view0  
Praktisch: aus unwrapped Phase mit Differenzenquotient (CJS beschreibt Unwrapping und numerische Ableitung explizit). citeturn17view0

Ein brauchbarer Stabilitätsindex ist z. B. die Winkelvarianz relativ zu on-axis:
\[
S_{GD,p}(f)=\sqrt{\frac{1}{N_\theta}\sum_i\left(\tau_{g,p}(f,\theta_i)-\tau_{g,p}(f,0)\right)^2}
\]
Bandgemittelt:
\[
S_{GD,p}=\sqrt{\frac{\sum_{f\in\mathcal{B}} w(f)S_{GD,p}(f)^2}{\sum w(f)}}
\]

**Was ist „gut/schlecht“ speziell für Hörner?**  
- **Gut**: moderate, glatte Winkelabhängigkeit; keine scharfen GD-Spikes innerhalb des Nutzbands.  
- **Schlecht**: starke GD-Ripple → Hinweis auf Mehrwege/Reflexionen/Moden. Die Interpretation muss aber vorsichtig sein: GD ist aus steady-state Phase abgeleitet und nicht identisch mit „echter Latenz“. citeturn20view0turn17view0

**Stabilität und Sensitivität**  
- **Ranking-Stabilität**: eher niedrig-mittel (phasensensitiv).  
- **Sehr empfindlich** auf Frequenz-Abtastung: wenn zwischen benachbarten Frequenzpunkten >180° Phasenänderung liegt, wird Unwrapping schwierig („Undersampling“-Problem). citeturn17view0  
Diese KPI ist deshalb **später** und eher als Diagnose-/Feintuning-Tool geeignet.

## Batch-Analyse und Scoring-Architektur für 200 Runs

### KPI-Schichtenmodell

Für 200 Runs pro Batch mit drei Ebenen (H/V/D) ist ein **mehrstufiges KPI-System** sinnvoll, das erst grob filtert, dann fein rankt, und Failure-Modes explizit markiert. Entscheidend: Ein einzelner Gesamtscore ohne „Flags“ ist gefährlich, weil Nebenkeulen/Reflexionen zwar selten, aber praxisdominant sein können. citeturn5view0

Ein praktikables Architekturprinzip ist:

**(A) Kurven-KPIs** pro Run (speicherbar als Arrays): \(BW_p(f)\), optional \(DI(f)\), \(E_{cov}(f)\), Flag-Funktionen.  
**(B) Band-KPIs** (skalare Werte): RMS, Bandbreiten, Max/Min, Perzentile.  
**(C) Flags/Constraints**: harte Ausschlusskriterien (z. B. „Beamwidth collapse > X°/Oktave“).  
**(D) Stage-spezifische Weight-Sets**: gleiche KPIs, aber andere Gewichtung je Entwicklungsphase.

### Filtering, Ranking, Outlier, Pareto

**Filtering (Constraints)**  
- Beamwidth-Treffer: \(|BW_H-BW^{tar}_H|\le 5^\circ\) und \(|BW_V-BW^{tar}_V|\le 5^\circ\) über mindestens \(B_{PC}\ge\) z. B. 2 Oktaven.  
- Kein starker Spill: \(R_{spill} < R_{max}\).  
- Keine harten Jumps/Collapses (Flags).

**Ranking (Score 0–100)**  
- Normalisiere jede Band-KPI robust im Batch (Median/MAD statt Mittelwert/Std, um Ausreißer zu dämpfen).  
- Score als gewichtete Summe plus Flag-Penalties:  
  \[
  Score = 100 - \sum_m w_m\,\text{penalty}_m - \sum_f w_f\,\text{flagPenalty}_f
  \]
- Wichtig: Penalties sollten **monoton** sein (besser → weniger Penalty) und bei „schlimm“ schnell saturieren (damit ein Run mit fataler Nebenkeule nicht durch andere gute Werte kompensiert wird). citeturn5view0

**Outlier Detection**  
- Robust z-score pro KPI: \(z=(x-\text{median})/(1.4826\,MAD)\).  
- Zusätzlich Outlier auf Kurven: DTW-ähnliche Distanz oder einfache „Curve residual energy“ gegen Batch-Median-Kurve von \(BW(f)\).

**Pareto-Front**  
Hörner sind typischerweise multi-objective: scharfer Roll-off vs Uniformität vs Pattern-Control-Bandbreite vs Ripple. Zusätzlich zeigt die Literatur, dass Direktivitätsfokus und Loading/Reflexionsverhalten in Spannung stehen. citeturn18view0turn16view1  
Daher: Pareto-Front z. B. für \((E_{BW}, E_{cov})\) oder \((R_{spill}, R_{off})\).

### Empfohlene KPI-Sets je Entwicklungsphase

**Core-KPIs für frühes Filtern (3–4 KPIs)**  
1) \(E_{BW,H}\) und \(E_{BW,V}\) (oder kombiniert) – „trifft das Horn die Zielabdeckung?“  
2) \(B_{PC}\) (min. Pattern-Control-Bandbreite) – „wie breitbandig ist das Pattern?“ citeturn6view0turn15view0  
3) Jump/Collapse-Flags (als harte Filter/hohe Penalty) – „keine instabilen Regimewechsel im Nutzband“  
4) \(R_{spill}\) oder \(Q_{beam}\) – „Energie außerhalb Coverage minimieren“ citeturn5view0

**Refinement-KPIs (3–4 KPIs)**  
1) \(E_{cov}\) – „Uniformität im Hörbereich“ (direkt von EAW motiviert). citeturn5view0  
2) \(S_{\theta}\) – „Polar-Smoothness“ (Nebenkeulen-/Interferenzindikator)  
3) \(E_{sym}\) (H/V/D-Konsistenz) – „Aspekt und Diagonal plausibel“  
4) \(R_{off}\) – „Frequenzripple off-axis“ (Resonanz-/Reflektionssensitiv) citeturn16view1turn18view0

**Fine-Tuning-KPIs (2–3 KPIs)**  
1) \(S_{DI}\) (auf gewählter DI-Variante) – „Direktivitätssmoothness“  
2) \(S_{GD}\) (optional) – „Phasen-/Zeitstabilität“ bei sauberer Phase/Resampling citeturn17view0turn20view0  
3) Diagonal-spezifische Checks (z. B. maximale Abweichung D vs „erwartete“ Interpolation H↔V), um „corner“-Moden/edge diffraction aufzuspüren.

## Wann zusätzliche Graph-Typen sinnvoll werden (über Polars hinaus)

### Wann SPL zusätzlich zu Polars erforderlich ist

Aus reinen Polars habt ihr zwar implizit On-Axis (θ=0) und Off-Axis-SPL, aber zweimal „SPL“ wird dann wichtig, wenn:

- **Absolute Pegel-/Effizienzvergleiche** zwischen Geometrien oder Projekten nötig sind (Polars können durch Normalisierung/Referenzierung diese Info verlieren).  
- **Resonanzdiagnose**: Peaks/Dips, die im On-Axis auftreten, sind für zusätzliche Diagnostik oft einfacher als über rein direktivitätsbezogene Normalisierung. Mundreflexionen erzeugen reale Peaks/Dips; Literatur beschreibt das als Folge von Reflexionen vom Mund zurück zum Throat. citeturn16view1turn18view0  
- **Driver+Horn vs Horn-only**: Wenn der Analyzer später Treiberkopplung berücksichtigen soll, ist die On-Axis-/Power-Response-Kurve als eigener Datentyp hilfreich.

### Wann Radiation Impedance nützlich wird

Radiation/Throat/Mouth-Impedanz ist dann wertvoll, wenn ihr **Resonanzen/Reflexionen** nicht nur sehen, sondern ursächlich bewerten wollt:

- Horn-Impedanz zeigt Real/Imag-Teile; für realistische Hornlängen treten Peaks/Dips durch Mundreflexionen auf, und es gibt eine „optimale“ Mundgröße zur Minimierung reflektierter Wellen. citeturn16view1turn15view0  
- Modellierung/Design nutzt häufig eine Mund-Randbedingung über Radiation Impedance (z. B. Piston-in-baffle als Näherung) und propagiert sie zur Throat-Input-Impedanz. citeturn22view0  
- Für Optimierung ist die Reflexionskennzahl über Impedanz sehr direkt: \(R=(Z-Z_0)/(Z+Z_0)\) wird in numerischer Hornoptimierung explizit als Zielgröße verwendet. citeturn23view0  

**Entwicklungsphase**: Resonanzkontrolle und Finale (wenn Directivity „gut genug“ ist und Loading/Reflexionen das nächste Limit werden). citeturn18view0turn16view1

### Wann Group Delay aus Phase kritisch wird

Group delay ist streng aus der Phase abgeleitet und braucht unwrapped, ausreichend fein abgetastete Phase; undersampling kann Unwrapping erschweren. citeturn17view0 Außerdem ist GD konzeptionell ein steady-state Maß und nicht automatisch „echte Latenz“. citeturn20view0 Kritisch wird GD vor allem, wenn:

- Ihr **interne Reflexionen/Mehrwege** erkennen wollt (GD-Spikes, Excess-phase).  
- Ihr **winkelabhängige Zeit-/Phasenstabilität** als Qualitätsmerkmal nutzt (später, nicht als Early Filter).  
- Ihr später **Crossover-/Systemintegration** ernsthaft im Tool abbilden wollt.

### Welche zusätzlichen Graph-Typen MT/HT-Hornentwicklung wirklich verbessern

Aus Sicht eines MT/HT-spezifischen Entwicklertools sind besonders wertvoll:

- **Throat/Input Impedance / Radiation Impedance / Reflection Coefficient**: direktes Fenster auf Loading/Reflexionen. citeturn22view0turn23view0turn16view1  
- **Aperture-/Mouth-Field (Pressure/Velocity Distribution)**: Diagnose von Moden/HOM und Kantenproblemen; zumindest als „Debug Export“ statt Voll-DB-Ingestion. (Die Literatur diskutiert, dass moderne Hörner teils Direktivität auf Kosten resonanter Loads erreichen; Feldbilder helfen hier, ohne Polars zu überinterpretieren.) citeturn18view0  

### Was in frühen Phasen eher „Noise“ ist

- Vollständige Impedanz-/Feld-Datenbanken für jeden Sweep-Run können in frühen Batches Overhead erzeugen, ohne die Kernentscheidung (Abdeckung & Stabilität) zu beschleunigen.  
- Phase-/GD-KPIs als Ranking-Kriterium in Phase „Konzept“ sind meist zu instabil (Sampling/Unwrapping/Referenz). citeturn17view0turn20view0

## Analyzer-UI und Datenpipeline

### MVP-Plots (müssen vorhanden sein)

1) **Polar-Heatmap/Contour** pro Ebene (H/V/D): \(L(f,\theta)\) als Farbfeld.  
   - Muss Normalisierungsmodus umschalten können: „On-axis“, „Max in ±X°“, „Power-normalized“ (weil Beamwidth/Q sonst irreführend). citeturn5view0  
2) **Beamwidth vs Frequency** (H/V/D Overlay) + Zielkurve + Toleranzband.  
3) **Coverage-Uniformity \(E_{cov}(f)\)** und/oder „RMS in Coverage“ vs Frequency (EAW-Logik). citeturn5view0  
4) **Scatter Plot für Batch** (mindestens 2D): z. B. \(E_{BW}\) vs \(R_{spill}\) oder \(B_{PC}\) vs \(E_{cov}\) für schnelle Pareto-Sicht.

### Advanced-Plots (Phase 2/3)

- **Nebenkeulen-Explorer**: Markiere Frequenzen/Winkel, in denen „Last-crossing“ stark von „First-crossing“ abweicht (Side-lobe-Diagnose). citeturn5view0  
- **DI-Kurve** (mit auswählbarer DI-Variante) + DI-Smoothness. citeturn2view0turn18view0  
- **Polar-Smoothness Maps**: \(\Delta^2_{\theta}L\) als Heatmap (Winkelkrümmung „wo“).  
- **Group Delay vs Frequency** (on-axis und off-axis) + GD-Stability-Heatmap (nur wenn Phasequalität gesichert). citeturn17view0turn20view0  
- **„Impulse aus Polar-Complex“** (IFFT) als Diagnose (nicht als Score), um Reflexionszeiten sichtbar zu machen.

### Welche KPIs als Tabellenspalten vs visuell

**Tabellenspalten (für Ranking/Filtering, scalar)**  
- \(E_{BW,H}\), \(E_{BW,V}\)  
- \(B_{PC,H}\), \(B_{PC,V}\) (oder kombiniert)  
- Jump/Collapse Count (Flags)  
- \(E_{cov,H}\), \(E_{cov,V}\)  
- \(R_{spill,H}\), \(R_{spill,V}\) (oder \(Q_{beam}\))  
- \(E_{sym,BW}\)  
- Optional: \(R_{off}\), \(S_{DI}\)

**Visuell (kurven-/feldbasiert, nicht als reine Zahl konsumierbar)**  
- Heatmaps (Polars)  
- Beamwidth-Kurven und Zielband  
- „First vs Last“-Beamwidth Overlay  
- GD/Phase-Darstellungen

### Band-Averaging und Frequenzgewichtung

Für MT/HT lohnt sich konsequent **logarithmische Gewichtung** (gleich pro Oktave), weil Hornphänomene (Mundgröße vs Wellenlänge, Moden) skaliert auftreten. citeturn6view0 Praktisch:

- Speichert pro KPI sowohl „full curve“ als auch Band-Summaries für feste Bänder (z. B. 1–2 kHz, 2–4 kHz, 4–8 kHz, 8–16 kHz) plus frei definierbar.  
- Für „Target horns“ (z. B. 90×40) sind bandgemittelte Zahlen oft aussagekräftiger als Einzelwerte.

### Analyzer-Architektur (SQL → compute → caching → UI)

**Datenfluss**  
1) SQL liefert \(P_p(f,\theta)\) als (freq, angle, Re, Im) pro Run/Ebene.  
2) Compute-Layer erzeugt:
   - Preprocessing: Magnitude/Phase, Normalisierungsvarianten, ggf. internes Resampling (Standard-Frequenzgrid)  
   - Kurven-KPIs (BW(f), E_cov(f), flags)  
   - Band-KPIs (RMS, bandwidths, max flags)  
3) Cache/Storage: Metrics-Tabellen + versionierte „algorithm revision id“.

**Precompute vs On-demand**  
- **Precompute (empfohlen)**: alles, was für Tabellenranking/Filter nötig ist (skalare KPIs + BW-Kurven). Mit 200 Runs pro Batch ist das die User-Experience-Entscheidung: Ranking sollte ohne „N+1“-Recomputes reagieren.  
- **On-demand**: schwere Diagnoseplots (GD-Heatmaps, IFFT-Impulse, komplexe DI-Approximationen), weil sie seltener gebraucht werden und phasen-/auflösungsabhängig sind. citeturn17view0turn14search27

**Cheap vs expensive (praktischer Maßstab)**  
- **Cheap**: \(BW(f)\), \(E_{BW}\), \(B_{PC}\), Jump/Collapse, \(E_{sym,BW}\) – reine Magnitude-Auswertung, \(O(N_f N_\theta)\).  
- **Mittel**: \(E_{cov}\), \(R_{spill}\), \(S_\theta\) – brauchen Coverage + Gewichtung, aber weiterhin magnitude-only. citeturn5view0turn2view0  
- **Teuer/fragil**: GD/Phase-KPIs (Unwrap + Ableitung + ggf. Delay removal), DI-Integrationen (3D-Rekonstruktion/Approx), Zeitdomäne. citeturn17view0turn20view0turn14search27

## Konkrete Empfehlungen für MVP, Phase 2 und Workflow

### Minimaler KPI-Satz für MVP (max. 5 KPIs)

Dieser Satz ist so gewählt, dass er (a) für MT/HT-Hörner direkt entscheidungsrelevant ist, (b) sehr stabil aus Magnitude-Polars berechenbar ist, und (c) frühe Entwicklung maximal beschleunigt:

1) **Pattern-Control-Bandbreite \(B_{PC}\)** (kombiniert H/V): „Wie viel Band wird wirklich kontrolliert?“ citeturn6view0turn15view0  
2) **Beamwidth-Target-Fehler \(E_{BW}\)** (H und V getrennt oder aggregiert): „Treffe ich 90×40 (oder Ziel) tatsächlich?“  
3) **Beamwidth-Jump/Collapse-Flags** (Penalty/Hard filter): „Instabilitäten eliminieren.“ citeturn15view0  
4) **Uniformität in Coverage \(E_{cov}\)** (H/V): RMS im Hörbereich (EAW-figure-of-merit). citeturn5view0  
5) **Spill-/Sidelobe-Index \(R_{spill}\) oder \(Q_{beam}\)**: „Wie viel Energie landet außerhalb?“ citeturn5view0

### Empfohlenes „Phase 2“-Set (Erweiterung)

Wenn MVP steht und die Ranking-/Filterlogik zuverlässig akzeptiert ist, erweitern diese KPIs die Diagnosefähigkeit deutlich:

- **Polar-Smoothness \(S_{\theta}\)** (Winkelkrümmung) – Nebenkeulen/Interferenzindikator. citeturn5view0  
- **Off-axis Ripple Index \(R_{off}\)** – resonanz-/reflexionssensitiv. citeturn16view1turn18view0  
- **DI-Smoothness \(S_{DI}\)** (mit klarer DI-Variante) – „polite directivity“. citeturn2view0turn18view0  
- **H/V/D-Formkonsistenz \(E_{sym,shape}\)** – diag als „corner detector“.  
- **Optional**: **Group-Delay-Stabilität \(S_{GD}\)**, aber nur, wenn ihr Phase-/Sampling sauber im Griff habt (Unwrapping/Resampling/Delay removal). citeturn17view0turn20view0

Parallel sinnvoll (nicht zwingend sofort DB-weit):  
- Ingestion **Radiation/Throat/Input Impedance** für Runs, die im Pareto-Top landen, um Resonanzursachen strukturiert diagnostizieren zu können. citeturn22view0turn23view0turn16view1

### Empfohlener Entwicklungsworkflow (KPI-Fokus über die Zeit)

**Frühe Iterationen (Konzept → Shaping)**  
- Zuerst ausschließlich: \(B_{PC}\), \(E_{BW}\), Jump/Collapse.  
- **Ignorieren**: DI-„Absolutwerte“, Off-axis Ripple, Phase/GD.  
- Wenn \(B_{PC}\) zu klein ist: Mundgröße/Abdeckung-Skalierung prüfen (klassischer Zusammenhang). citeturn6view0

**Mittlere Iterationen (Stabilisierung)**  
- Fokus: \(E_{cov}\) + \(R_{spill}\) + Flags.  
- Hier entscheidet sich Arrayability und „keine Energie außerhalb“; EAW zeigt, dass klassische Definitionen sonst zu optimistisch sein können, deshalb sind RMS/Spill-Kennzahlen zentral. citeturn5view0

**Späte Iterationen (Resonanzkontrolle → Finale)**  
- Fokus: \(S_{\theta}\), \(R_{off}\), \(S_{DI}\); optional \(S_{GD}\) als Diagnose.  
- Wenn Ripple/GD auffällig: gezielt weitere Graph-Typen (Impedanz/Reflection/Field) ziehen, statt Polars „zu überdehnen“. Mundreflexionen und resonante Loads sind dokumentierte Ursachen für Peaks/Dips. citeturn16view1turn18view0turn22view0

**Prinzip „wann ignorieren“**  
- Wenn ein Run das Ziel-Pattern nicht trifft (großes \(E_{BW}\) oder schlechtes \(B_{PC}\)), sind Feinkennzahlen (DI-Smoothness, GD) meistens **Zeitverschwendung**: die Geometrie ist noch in der falschen Größenordnung.  
- Wenn das Pattern stimmt, aber Spill/RMS schlecht ist, sind weitere „Beamwidth“-Optimierungen oft nur Kosmetik; dann ist Nebenkeulen-/Reflektionskontrolle der Hebel. citeturn5view0turn16view1
