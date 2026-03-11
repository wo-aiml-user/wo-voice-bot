"""
All tool schemas for DeepSeek function calling.
Includes: retrieval tool.
"""

# Retrieval tool schema
retrieval_tool = {
    "type": "function",
    "function": {
        "name": "retrieve_documents",
        "description": "Retrieve relevant information from the knowledge base to answer user questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant documents"
                },
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of specific file IDs to search within"
                }
            },
            "required": ["query"]
        }
    }
}
