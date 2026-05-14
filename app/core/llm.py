import logging
import litellm

logger = logging.getLogger(__name__)

def register_custom_models():
    """Register models that are not yet in the static litellm registry."""
    
    # Qwen 3.6 Plus - registered via OpenAI compatible adapter for DashScope
    # Using 128k context window as a safe default for modern Qwen models
    custom_models = {
        "openai/qwen3.6-plus": {
            "max_tokens": 128000,
            "input_cost_per_token": 0.0000002, # Estimated cost
            "output_cost_per_token": 0.0000006, # Estimated cost
            "litellm_provider": "openai",
            "mode": "chat"
        },
        "openai/qwen3.6-72b-instruct": {
            "max_tokens": 128000,
            "input_cost_per_token": 0.0000004,
            "output_cost_per_token": 0.0000012,
            "litellm_provider": "openai",
            "mode": "chat"
        }
    }
    
    try:
        litellm.register_model(custom_models)
        logger.info("Successfully registered custom models in LiteLLM: %s", list(custom_models.keys()))
    except Exception as e:
        logger.error("Failed to register custom models in LiteLLM: %s", e)

def init_llm():
    """Initialize LiteLLM settings and custom models."""
    litellm.drop_params = True
    register_custom_models()
