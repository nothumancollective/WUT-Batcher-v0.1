# Codex Prompt Template

Kontext:
- Version = eine konkrete ATH-Parameter-Kombination -> ein konkretes Horn.
- Runner/Creator sind stabil und werden als Blackbox per subprocess aufgerufen.
- GUI ist nur Orchestrator, keine UI-Automation.

Aufgabe:
- Beschreibe die zu implementierende, klar abgegrenzte Teilaufgabe.

Constraints:
- Keine grossen Refactors.
- Nur die vereinbarten Dateien aendern.
- Platform-Checks beibehalten; Windows-Lauf darf nicht eingeschraenkt werden.

Akzeptanzkriterien:
- 3-8 messbare Punkte, die direkt testbar sind.

Output:
- Liste geaenderter/neu erstellter Dateien.
- Kurze Anleitung fuer manuellen Test (CLI-Befehle).
