from groq import Groq
import config


def chat_completion(messages: list[dict], model: str = None) -> str:
    """
    Executes a chat completion call using the Groq Python SDK.
    """
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in environment or .env file.")

    client = Groq(api_key=config.GROQ_API_KEY)
    model_to_use = model or config.GROQ_MODEL_REASONING

    response = client.chat.completions.create(
        model=model_to_use,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=config.GROQ_TEMPERATURE,
        max_tokens=config.GROQ_MAX_TOKENS,
    )
    return response.choices[0].message.content
