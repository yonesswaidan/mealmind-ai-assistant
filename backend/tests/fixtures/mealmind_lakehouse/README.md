# Testfixture: lokalt MealMind-lakehouse (serving-udtræk)

Skrevet af den rigtige lokale pipeline i `biteowl/data-platform` (eksport → Bronze → Silver → ML → Gold →
serving) ud fra dens håndskrevne testdatabase (`tests/conftest.py`). Indholdet er **syntetisk**
(`contains_synthetic_data: true`), pseudonymiseret med en testnøgle og indeholder ingen rigtige brugerdata.
Bruges til at sikre, at MealMind Insights læser Silver- og Gold-tabeller fra det lokale lakehouse og aldrig
præsenterer dem som kørt i Azure Databricks.

Regenerér efter ændringer i datakontrakten eller pipelinen (fra `biteowl/data-platform`):

    .venv/bin/python scripts/build_insights_lakehouse_fixture.py \
      /sti/til/mealmind-ai-assistant/backend/tests/fixtures/mealmind_lakehouse
