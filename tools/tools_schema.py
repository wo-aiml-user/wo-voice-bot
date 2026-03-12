"""
All tool schemas for Deepgram Voice Agent function calling.
"""

# Retrieval tool schema - Deepgram Voice Agent flat format
# NOTE: No endpoint is provided, so this is a client-side function per Deepgram docs.
retrieval_tool = {
    "name": "retrieve_documents",
    "description": (
        "Retrieve relevant information from the knowledge base to answer user questions. "
        "Call this function before answering any question about the company."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant documents"
            }
        },
        "required": ["query"]
    }
}
