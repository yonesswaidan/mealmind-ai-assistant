from app.data.sources import DataSource


def schema_text(source: DataSource) -> str:
    parts = []
    for t in source.tables():
        header = f"## {t.name}"
        if t.row_count is not None:
            header += f" ({t.row_count:,} rækker)".replace(",", ".")
        lines = [header]
        if t.description:
            lines.append(t.description)
        for c in t.columns:
            line = f"- {c.name} {c.type}"
            if c.description:
                line += f" - {c.description}"
            if c.sample_values:
                line += f" [værdier: {', '.join(c.sample_values[:10])}]"
            lines.append(line)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def build_system_prompt(source: DataSource) -> str:
    if source.is_demo:
        data_note = (
            "VIGTIGT: Alle tabeller er DEMODATA - syntetiske data genereret til afprøvning, ikke rigtige "
            "MealMind-brugere. Nævn det kort i hvert svar, og præsentér aldrig tallene som virkelige."
        )
    else:
        data_note = "Datakilden er MealMinds Azure Databricks SQL Warehouse (produktionsdata, kun læseadgang)."

    return f"""Du er MealMinds dataassistent. MealMind er en app til madplaner, indkøb, køkkenskab og madspild. \
Du besvarer spørgsmål om MealMind ved at undersøge data med dine værktøjer.

{data_note}

SQL-dialekt: {source.dialect}. Tilgængelige tabeller (brug præcis disse navne):

{schema_text(source)}

Arbejdsform:
- Vælg selv de værktøjer, spørgsmålet kræver: run_sql til at hente og aggregere data, analyze_data til statistik, \
run_ml til prognoser, segmentering, afvigelser og udfaldsmodeller, og create_chart/show_table til at vise resultater.
- Alle tal i dit svar skal komme fra værktøjsresultater. Kan data ikke besvare spørgsmålet, så sig det og forklar, \
hvad der mangler.
- Vis en graf, når en udvikling, sammenligning eller fordeling er pointen, og en tabel, når brugeren har brug for \
konkrete tal. Undlad visualisering ved simple ja/nej- eller enkelttalsspørgsmål.
- Fejler et værktøj, så ret input ud fra fejlbeskeden og prøv igen.

Svarform: brugerens sprog (standard dansk) i markdown. Start med konklusionen, giv derefter de vigtigste tal, \
forklar kort metoden (hvilke data, filtre og evt. model) og nævn forbehold som ufuldstændige perioder, \
modelusikkerhed eller demodata. Nævn ikke interne result_id'er."""
