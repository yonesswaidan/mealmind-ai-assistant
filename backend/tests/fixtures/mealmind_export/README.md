# Testfixture: MealMind-udtræk

Lavet med den rigtige eksport i `biteowl/data-platform` (`export_extract`) ud fra dens håndskrevne
testdatabase. Indholdet er **syntetisk** (`contains_synthetic_data: true`), pseudonymiseret med en
testnøgle og indeholder ingen rigtige brugerdata. Bruges til at sikre, at AIDA kan læse præcis det format,
som MealMind-eksporten skriver (typer, tidszoner, manifest og checksummer).

Regenerér efter ændringer i datakontrakten (fra `biteowl/data-platform`):

    python -c "import sys; sys.path.insert(0,'tests'); from pathlib import Path; from conftest import *; \
    from mealmind_data.readers import read_source; from mealmind_data.export import export_extract; \
    export_extract(read_source(str(build_fixture_db(Path('/tmp/fx.db')))), Path('/tmp/fx'), \
    key='fixture-only-key-not-secret-0123456789abcdef', snapshot_at=SNAPSHOT, synthetic=True)"
