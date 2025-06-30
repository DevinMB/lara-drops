import requests
import os
import logging

OLLAMA_HOST = os.getenv("AI_NODE_ADDRESS", "http://192.168.10.7:11434")

def generate_summary(added, removed):
    added_section = ""
    removed_section = ""

    if not added.empty:
        logging.info("Newly Added DataFrame to AI:\n" + added.to_string(index=False))
        added_section = (
            "Write a clever and engaging summary about these *new whiskeys* as if it's a mixtape just dropped. Use emojis and cool slang. Keep it fun and simple. Must include price.\n\n"
            "### New Whiskeys:\n"
            f"{added[['CODE', 'Brand', 'Proof', 'List Price', 'Category']].head(5).to_string(index=False)}"
        )

    if not removed.empty:
        logging.info("Removed DataFrame to AI:\n" + removed.to_string(index=False))
        removed_section = (
            "Write a heartfelt eulogy for these *discontinued whiskeys*. Make it poetic and nostalgic.\n\n"
            "### Discontinued Whiskeys:\n"
            f"{removed[['CODE', 'Brand', 'Proof', 'List Price', 'Category']].head(5).to_string(index=False)}"
        )

    responses = []

    for section in [added_section, removed_section]:
        if section:
            try:
                response = requests.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={"model": "mistral", "prompt": section, "stream": False},
                    timeout=30
                )
                response.raise_for_status()
                result = response.json()
                responses.append(result.get("response", "No response generated."))
            except Exception as e:
                responses.append(f"Error calling Ollama API: {e}")

    return "\n\n---\n\n".join(responses)
