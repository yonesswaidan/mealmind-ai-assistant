import hmac
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.agent.agent import AgentDeps, ChatRequest, run_agent
from app.agent.llm import create_llm, credentials_available
from app.agent.prompts import build_system_prompt
from app.config import Settings, get_settings
from app.overview import build_overview
from app.data.sources import DatabricksSource, DataSource, QueryError, create_source
from app.tools.ml import build_registry
from app.tools.registry import tool_definitions

log = logging.getLogger("insights")


def open_source(settings: Settings) -> tuple[DataSource, dict]:
    """Åbner datakilden, indlæser skemaet og kontrollerer at Databricks-identiteten kun kan læse."""
    source = create_source(settings)
    source.tables()  # indlæs skema ved opstart, så første spørgsmål ikke venter
    status: dict = {"source_error": None, "read_only_check": None}
    if isinstance(source, DatabricksSource):
        report = source.privilege_report()
        status["read_only_check"] = report
        if report["status"] == "write_access":
            if settings.databricks_enforce_read_only:
                raise QueryError(report["message"] + " MealMind Insights starter ikke med en identitet, der kan skrive "
                                 "(DATABRICKS_ENFORCE_READ_ONLY=true).")
            log.warning(report["message"])
    return source, status


def _execution_info(source: DataSource) -> dict | None:
    """Hvor et lokalt lakehouse er beregnet (motor, MLflow-eksperiment, tidspunkt). Ingen stier eller nøgler."""
    execution = getattr(source, "execution", None) or {}
    if not execution:
        return None
    return {k: execution.get(k) for k in ("environment", "engine", "description", "mlflow_experiment", "trained_at")}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            source, status = open_source(settings)
        except (ValueError, QueryError) as e:
            if not (settings.allow_demo_fallback and settings.data_source != "demo"):
                raise RuntimeError(f"Datakilden '{settings.data_source}' kunne ikke åbnes: {e}") from e
            log.error("Datakilden '%s' kunne ikke åbnes - bruger DEMODATA: %s", settings.data_source, e)
            source, status = open_source(settings.model_copy(update={"data_source": "demo"}))
            status["source_error"] = (f"Datakilden '{settings.data_source}' kunne ikke åbnes: {e} "
                                      "MealMind Insights kører midlertidigt på DEMODATA.")
        app.state.source_status = status
        registry = build_registry(settings)
        if settings.assistant_test_mode:
            from app.agent.scripted import ScriptedLLM

            llm = ScriptedLLM(source)
        else:
            llm = create_llm(settings)
        app.state.deps = AgentDeps(settings, source, registry, llm, build_system_prompt(source),
                                   tool_definitions(registry))
        yield

    app = FastAPI(title="MealMind Insights", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    def require_token(request: Request) -> None:
        if not settings.app_access_token:
            return
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(token.encode(), settings.app_access_token.encode()):
            raise HTTPException(status_code=401, detail="Adgangstoken mangler eller er forkert.")

    hits: dict[str, deque] = defaultdict(deque)

    def rate_limit(request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        if len(hits) > 10_000:
            for k in [k for k, v in hits.items() if not v or now - v[-1] > 60]:
                del hits[k]
        q = hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="For mange forespørgsler. Vent et øjeblik.")
        q.append(now)

    @app.get("/api/health")
    def health(request: Request):
        deps: AgentDeps = request.app.state.deps
        return {
            "status": "ok",
            "data_source": deps.source.kind,
            "data_label": deps.source.label,
            "demo": deps.source.is_demo,
            "execution_environment": deps.source.execution_environment,
            "execution": _execution_info(deps.source),
            "llm_configured": settings.assistant_test_mode or credentials_available(settings),
            "provider": "test" if settings.assistant_test_mode else settings.ai_provider,
            "model": "scripted-test" if settings.assistant_test_mode else settings.llm_model,
            "test_mode": settings.assistant_test_mode,
            "auth_required": bool(settings.app_access_token),
            "source_error": request.app.state.source_status["source_error"],
            "read_only_check": request.app.state.source_status["read_only_check"],
        }

    @app.get("/api/datasets", dependencies=[Depends(require_token)])
    def datasets(request: Request):
        deps: AgentDeps = request.app.state.deps
        return {
            "demo": deps.source.is_demo,
            "data_source": deps.source.kind,
            "data_label": deps.source.label,
            "tables": [{
                "name": t.name, "description": t.description, "row_count": t.row_count,
                "columns": [{"name": c.name, "type": c.type, "description": c.description,
                             "sample_values": c.sample_values[:6]} for c in t.columns],
            } for t in deps.source.tables()],
            "ml_functions": [{"name": f.name, "description": f.description} for f in deps.ml_registry.values()],
        }

    @app.get("/api/overview", dependencies=[Depends(require_token)])
    def overview(request: Request):
        deps: AgentDeps = request.app.state.deps
        return build_overview(deps.source, deps.ml_registry)

    @app.post("/api/chat", dependencies=[Depends(require_token), Depends(rate_limit)])
    async def chat(body: ChatRequest, request: Request):
        deps: AgentDeps = request.app.state.deps

        async def events():
            try:
                async for event in run_agent(body, deps):
                    if await request.is_disconnected():
                        return
                    yield {"data": json.dumps(event, ensure_ascii=False)}
            except Exception:
                log.exception("Uventet fejl i agenten")
                yield {"data": json.dumps({"type": "error", "message": "Der opstod en intern fejl."})}

        return EventSourceResponse(events(), ping=15)

    dist = settings.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
