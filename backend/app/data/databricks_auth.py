"""Godkendelse mod Azure Databricks: OAuth M2M med en service principal (anbefalet) eller et adgangstoken.

Hemmelighederne læses kun fra miljøvariabler og logges eller returneres aldrig til frontend.
"""

from app.config import Settings


class DatabricksConfigError(ValueError):
    pass


def auth_mode(settings: Settings) -> str:
    if settings.databricks_client_id and settings.databricks_client_secret:
        return "oauth_m2m"
    if settings.databricks_token:
        return "token"
    raise DatabricksConfigError(
        "Databricks-adgang mangler: sæt DATABRICKS_CLIENT_ID og DATABRICKS_CLIENT_SECRET (service principal, "
        "anbefalet) eller DATABRICKS_TOKEN."
    )


def _sdk_config(settings: Settings):
    from databricks.sdk.core import Config

    return Config(host=f"https://{settings.databricks_server_hostname}", client_id=settings.databricks_client_id,
                  client_secret=settings.databricks_client_secret)


def sql_connect_kwargs(settings: Settings) -> dict:
    """Argumenter til databricks.sql.connect() ud over hostname/http_path."""
    if auth_mode(settings) == "token":
        return {"access_token": settings.databricks_token}
    from databricks.sdk.core import oauth_service_principal

    return {"credentials_provider": lambda: oauth_service_principal(_sdk_config(settings))}


def rest_headers(settings: Settings) -> dict[str, str]:
    """HTTP-headers til Databricks REST (fx Model Serving)."""
    if auth_mode(settings) == "token":
        return {"Authorization": f"Bearer {settings.databricks_token}"}
    return dict(_sdk_config(settings).authenticate())
