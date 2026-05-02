import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from app.config import settings

async def main():
    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    
    prompt = """<|start_header_id|>system<|end_header_id|>

You are a function calling AI model. You are provided with function signatures within <tools></tools> XML tags. You may call one or more functions to assist with the user query. Don't make assumptions about what values to plug into functions. For each function call return a json object with function name and arguments within <tool_call></tool_call> XML tags as follows:
<tool_call>
{"name": <function-name>,"arguments": <args-dict>}
</tool_call>

Here are the available tools:
<tools> {
    "name": "get_current_weather",
    "description": "Get the current weather in a given location",
    "parameters": {
        "properties": {
            "location": {
                "description": "The city and state, e.g. San Francisco, CA",
                "type": "string"
            },
            "unit": {
                "enum": [
                    "celsius",
                    "fahrenheit"
                ],
                "type": "string"
            }
        },
        "required": [
            "location"
        ],
        "type": "object"
    }
} </tools><|eot_id|><|start_header_id|>user<|end_header_id|>

What is the weather like in San Francisco?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"""

    print("Testing raw completion endpoint...")
    try:
        resp = await client.completions.create(
            model=settings.arbiter_model,
            prompt=prompt,
            max_tokens=200,
            temperature=0.0
        )
        print("Response:\n", resp.choices[0].text)
    except Exception as e:
        print("Error with completions:", e)
        
    print("\nTesting chat endpoint with string roles...")
    try:
        resp = await client.chat.completions.create(
            model=settings.arbiter_model,
            messages=[
                {"role": "system", "content": prompt.split("<|eot_id|>")[0].replace("<|start_header_id|>system<|end_header_id|>\n\n", "")},
                {"role": "user", "content": "What is the weather like in San Francisco?"}
            ],
            max_tokens=200,
            temperature=0.0
        )
        print("Response:\n", resp.choices[0].message.content)
    except Exception as e:
        print("Error with chat:", e)

if __name__ == "__main__":
    asyncio.run(main())
