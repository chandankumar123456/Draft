import os

from config import ensure_loaded

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

ensure_loaded()

# Create credential
credential = DefaultAzureCredential()

def get_project_client(endpoint: str | None = None) -> AIProjectClient | None:
    """Create or return an AIProjectClient instance."""
    ep = endpoint or os.getenv("PROJECT_ENDPOINT")
    if not ep:
        return None
    try:
        return AIProjectClient(
            endpoint=ep,
            credential=credential
        )
    except Exception:
        return None

def get_openai_client(endpoint: str | None = None):
    """Create or return an OpenAI client from the AI project client."""
    client = get_project_client(endpoint)
    if client is not None:
        try:
            return client.get_openai_client()
        except Exception:
            return None
    return None

# Module-level references
project_endpoint = os.getenv("PROJECT_ENDPOINT")
model_deployment = os.getenv("MODEL_DEPLOYMENT")

try:
    project_client = get_project_client(project_endpoint) if project_endpoint else None
    openai_client = get_openai_client(project_endpoint) if project_endpoint else None
except Exception:
    project_client = None
    openai_client = None
