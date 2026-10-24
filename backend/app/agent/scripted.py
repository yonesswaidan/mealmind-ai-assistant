"""Scriptet LLM til automatiske tests (INSIGHTS_TEST_MODE, tidligere ASSISTANT_TEST_MODE). Kalder de rigtige værktøjer, men beslutter ikke selv.

Bruges aldrig i normal drift; svaret markeres tydeligt med [Testtilstand].
"""

import json

from app.agent.llm import TextCallback, ToolUse, Turn
from app.agent.router import plan_question
from app.data.sources import DataSource


class ScriptedLLM:
    def __init__(self, source: DataSource):
        table = source.tables()[0]
        date_col = next((c.name for c in table.columns if c.type.upper().startswith(("DATE", "TIMESTAMP"))), None)
        if date_col is None:
            raise ValueError("Testtilstand kræver en dato-kolonne i første tabel.")
        self.table = table.name
        self.date_col = date_col

    async def turn(self, *, system: str, tools: list[dict], messages: list[dict], on_text: TextCallback) -> Turn:
        results = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        n = len(results)
        question = next(m["content"] for m in reversed(messages)
                        if m["role"] == "user" and isinstance(m["content"], str)).split("\n\n[Systemhint")[0]
        if "forecast_timeseries" in plan_question(question).ml_functions:
            return await self._forecast_flow(results, on_text)
        if n == 0:
            return self._tool("run_sql", {
                "sql": f"SELECT date_trunc('month', {self.date_col}) AS month, COUNT(*) AS rows "
                       f"FROM {self.table} GROUP BY 1 ORDER BY 1",
                "title": "Rækker pr. måned",
            }, n)
        if n == 1:
            rid = json.loads(results[0]["content"])["result_id"]
            return self._tool("create_chart", {
                "result_id": rid, "chart_type": "line", "x": "month", "y": ["rows"], "title": "Rækker pr. måned",
            }, n)
        if n == 2:
            return self._tool("show_table", {"result_id": "r1", "title": "Rækker pr. måned"}, n)

        sql_result = json.loads(results[0]["content"])
        total = sum(r["rows"] for r in sql_result["preview"])
        text = (f"[Testtilstand] {self.table} har {total} rækker fordelt på "
                f"{sql_result['row_count']} måneder (demodata).")
        for i in range(0, len(text), 20):
            await on_text(text[i:i + 20])
        return Turn(content=[{"type": "text", "text": text}], stop_reason="end_turn", tool_uses=[])

    async def _forecast_flow(self, results: list[dict], on_text: TextCallback) -> Turn:
        """Prognose-spørgsmål: SQL → ML-prognose → graf → forklaring ud fra de beregnede tal."""
        n = len(results)
        if n == 0:
            return self._tool("run_sql", {
                "sql": f"SELECT date_trunc('week', {self.date_col}) AS week, COUNT(*) AS rows "
                       f"FROM {self.table} GROUP BY 1 ORDER BY 1",
                "title": "Rækker pr. uge",
            }, n)
        if n == 1:
            rid = json.loads(results[0]["content"])["result_id"]
            return self._tool("run_ml", {"function": "forecast_timeseries", "params": {
                "result_id": rid, "date_column": "week", "value_column": "rows", "freq": "W", "horizon": 4}}, n)
        ml = json.loads(results[1]["content"])
        if n == 2:
            return self._tool("create_chart", {
                "result_id": ml["results"][0]["result_id"], "chart_type": "line", "x": "period",
                "y": ["actual", "forecast"], "title": "Prognose pr. uge"}, n)
        s = ml["summary"]
        text = (f"[Testtilstand] Prognosen for næste uge er {s['next_period_forecast']:.0f} rækker "
                f"(model: {s['model']}, backtest MAE {s['backtest_mae']:.1f}).")
        await on_text(text)
        return Turn(content=[{"type": "text", "text": text}], stop_reason="end_turn", tool_uses=[])

    def _tool(self, name: str, args: dict, n: int) -> Turn:
        block = {"type": "tool_use", "id": f"toolu_test_{n}", "name": name, "input": args}
        return Turn(content=[block], stop_reason="tool_use", tool_uses=[ToolUse(block["id"], name, args)])
