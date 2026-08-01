from opentalking.providers.llm.openai_compatible.conversation import ConversationHistory
from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient
from opentalking.providers.llm.openai_compatible.sentence_splitter import SentenceSplitter

# Side-effect import: registers ``openclaw_agent`` in the capability registry
# so ``opentalking.core.registry.resolve("llm", "openclaw_agent")`` returns
# the OpenClaw-gateway-backed LLM client after ``opentalking.providers.bootstrap()``.
from opentalking.agent.openclaw_provider import (  # noqa: E402, F401
    OpenClawAgentLLMClient,
    OpenClawAgentConfigError,
    build_openclaw_agent_client,
)

__all__ = [
    "ConversationHistory",
    "OpenAICompatibleLLMClient",
    "SentenceSplitter",
    "OpenClawAgentLLMClient",
    "OpenClawAgentConfigError",
    "build_openclaw_agent_client",
]
