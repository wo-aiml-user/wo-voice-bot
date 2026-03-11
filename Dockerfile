# Use an official Python runtime as a base image
FROM python:3.12.9-slim

# Set the working directory
WORKDIR /app

# Install only required LibreOffice packages for DOCX to PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-common \
    libreoffice-writer \
    libreoffice-java-common \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies and SpaCy small model
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

# Copy the rest of the application files
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8000

# Run the app
CMD ["python", "uvicorn_config.py"]