# FastAPI Project Setup Guide

## Prerequisites

Ensure you have the following installed:
- **Python 3.8+**
- **pip** (Python package manager)
- **virtualenv** (optional but recommended)

---

## Setup Instructions

### Clone the Repository
```bash
git clone https://github.com/your-repo/your-project.git
cd your-project
```

### Create a Virtual Environment
#### Windows
```powershell
python -m venv venv
venv\Scripts\activate
```

#### Linux / macOS
```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

## Dependencies

Setup Spacy
pip install spacy --break-system-packages
python3 -m spacy download en_core_web_sm

Setup Tika
sudo docker run -d -p 127.0.0.1:9998:9998 apache/tika:latest-full 

Handle docx files
sudo apt install libreoffice

Setup Milvus via Docker
curl -sfL https://raw.githubusercontent.com/milvus-io/milvus/master/scripts/standalone_embed.sh -o standalone_embed.sh

Start the Docker container
bash standalone_embed.sh start
---

## Docker Deployment (Recommended)

Ensure you have Docker and Docker Compose installed.

### Build and Run
```bash
sudo docker-compose build
sudo docker-compose down
sudo docker-compose up -d
```

Once the containers are up, access the API docs:
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

Docker Compose will start the FastAPI app and a Tika server. Environment variables can be provided via a `.env` file in the project root (see the Environment Variables section below).

---

## Running the Server
```bash
python uvicorn_config.py
```

---

##  Running in Production

Prefer the Docker-based approach above for production. If you need to run without Docker, a `uvicorn_config.py` file is included:

```bash
python uvicorn_config.py
```

---

##  Environment Variables
You can configure environment-specific settings using a `.env` file.
Create a **.env** file in the project root as `.env.example`.

---


## Project Structure

```
tool_calling/
├── app/
│   ├── api/
│   │   ├── auth/              # Authentication endpoints
│   │   │   ├── auth_controller.py # Login & Registration logic
│   │   │   ├── auth_model.py      # User & Token Pydantic models
│   │   │   └── token.py           # JWT Token generation
│   │   ├── chat/              # Chat API endpoints and service logic
│   │   │   ├── services/      # Core chat logic (chat_service.py)
│   │   │   └── models/        # Pydantic models for chat
│   │   ├── document/          # Document upload and processing API
│   │   │   ├── services/      # PDF processing logic (pdf_operation.py)
│   │   │   └── models/        # Document models
│   │   └── voice/             # Voice API endpoints (Deepgram integration)
│   │       ├── services/      # Voice session & streaming (voice_session.py, voice_service.py)
│   │       ├── models/        # Pydantic models for voice (voice_model.py)
│   │       └── voice_controller.py  # Voice WebSocket endpoints
│   ├── middleware/            # Application Middleware
│   │   ├── jwt_auth.py        # JWT Authentication Middleware
│   │   └── logging.py         # Request/Response Logging
│   ├── RAG/                   # RAG Pipeline Components
│   │   ├── rag_chain.py       # Main orchestration logic (LLM + Tools)
│   │   ├── embedding.py       # Document embedding logic (Voyage AI)
│   │   ├── chunking.py        # Text chunking strategies
│   │   ├── vector_store.py    # Milvus connection utilities
│   │   ├── deepseek_client.py # DeepSeek API client
│   │   └── prompt.py          # System prompts for the LLM
│   ├── utils/
│   │   ├── response_formatter.py # Logic for formatting LLM responses and metadata
│   │   └── json_parser.py     # Utilities for parsing LLM JSON output
│   ├── config.py              # Application configuration (loads .env)
│   └── main.py                # FastAPI entry point
├── tools/
│   ├── functions.py           # Tool implementations (Weather, Search, Retrieval)
│   └── tools_schema.py        # JSON schemas for function calling
├── logs/                      # Application logs
├── .env.example               # Template for environment variables
├── requirements.txt           # Python dependencies
├── uvicorn_config.py          # Server startup configuration
└── docker-compose.yml         # Container orchestration (Milvus, Tika)
```

## API Documentation
Once the server is running, access the API docs:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)