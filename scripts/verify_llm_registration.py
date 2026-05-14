import os
import sys

# Add project root to path to ensure imports work
sys.path.append(os.getcwd())

from app.core.llm import init_llm
import litellm

def verify():
    print("Initializing LLM metadata...")
    init_llm()
    
    model = "openai/qwen3.6-plus"
    print(f"Checking model info for {model}...")
    
    try:
        info = litellm.get_model_info(model)
        print("\n[SUCCESS] Model metadata found:")
        print(f" - Max Tokens: {info.get('max_tokens')}")
        print(f" - Provider: {info.get('litellm_provider')}")
        print(f" - Mode: {info.get('mode')}")
    except Exception as e:
        print(f"\n[FAILURE] Could not retrieve info for {model}: {e}")
        sys.exit(1)

    print("\nTesting token counter fallback...")
    from pageindex.utils import count_tokens
    test_text = "Hello world! 你好，世界！"
    token_count = count_tokens(test_text, model=model)
    print(f"Token count for '{test_text}': {token_count}")
    
    if token_count > 0:
        print("[SUCCESS] Token counting works.")
    else:
        print("[FAILURE] Token counting returned 0.")
        sys.exit(1)

if __name__ == "__main__":
    verify()
