"""Provider-neutral LLM boundary; see ``providers.groq`` for its adapter."""

from research_agent.interfaces import LLMClient
from research_agent.models import LLMResponse

__all__ = ["LLMClient", "LLMResponse"]
