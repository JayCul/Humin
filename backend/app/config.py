"""Central configuration for the Humin backend.

Everything is read from environment variables (see .env.example). The service
is designed to run fully in "mock mode" with zero external credentials so the
agent loop is demoable offline, then flip to real CockroachDB Cloud + Bedrock
once credentials are supplied.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Humin"
    environment: str = "local"
    cors_origins: str = "http://localhost:3000"

    # --- CockroachDB ---
    # Standard CockroachDB Cloud connection string, e.g.:
    # postgresql://<user>:<password>@<host>:26257/<database>?sslmode=verify-full
    cockroachdb_url: str = ""
    # CockroachDB Cloud Managed MCP Server. The endpoint is a single shared
    # URL across all customers/clusters - which cluster you mean is carried
    # in the `mcp-cluster-id` header, not the URL itself, so it has a real
    # default here. What actually gates whether MCP is "configured" (see
    # mcp_client.is_configured()) is the cluster ID + a service-account API
    # key, both per-deployment and required together.
    cockroachdb_mcp_url: str = "https://cockroachlabs.cloud/mcp"
    cockroachdb_cluster_id: str = ""
    cockroachdb_mcp_api_key: str = ""
    # The MCP server's query tool takes a database name as a required
    # argument alongside the query text - matches the database in
    # cockroachdb_url.
    cockroachdb_database: str = "defaultdb"

    # --- AWS / Bedrock ---
    aws_region: str = "us-east-1"
    bedrock_text_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    # Titan Image Generator isn't offered in every account/region; Nova
    # Canvas is Amazon's current text-to-image model and shares the same
    # taskType/textToImageParams/imageGenerationConfig request shape, so
    # generate_image() needs no code change if this ever has to switch back.
    bedrock_image_model_id: str = "amazon.nova-canvas-v1:0"
    embedding_dimensions: int = 1024  # Titan Embed Text v2 default output dim

    # --- Trend signal (real, read-only external grounding source) ---
    trends_provider: str = "mock"  # "mock" | "google_trends"

    # --- Mock switches (keep the demo runnable with no cloud creds) ---
    use_mock_llm: bool = True
    use_mock_db: bool = True

    # --- In-app scheduler (demo path to "autonomous"; see app/scheduler.py) ---
    scheduler_default_interval_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
