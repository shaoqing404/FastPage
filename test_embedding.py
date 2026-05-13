import requests
import json
import os

url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
api_key = "your_api_key_here"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

data = {
    "model": "text-embedding-v4",
    "input": ["这是一个关于嵌入测试的示例文档。"]
}

print(f"Sending request to {url}...")
response = requests.post(url, headers=headers, json=data)

print(f"Status Code: {response.status_code}")
if response.status_code == 200:
    res_json = response.json()
    embeddings = res_json.get("data", [])
    if embeddings:
        print(f"Success! Retrieved {len(embeddings)} embedding(s).")
        print(f"Dimensions of first embedding: {len(embeddings[0].get('embedding', []))}")
    else:
        print("Success, but no embedding data returned.")
        print(response.text)
else:
    print("Error:")
    print(response.text)
