# NetGraphX - Mentor Review Environment

This package contains the complete NetGraphX Network Intelligence Dashboard, along with a pre-configured database dump to ensure you have the exact topology and ML models ready for testing.

## Prerequisites
- Docker Desktop (or Docker Engine + Docker Compose) installed and running.
- Ensure ports 8501, 5001, 8081, 7474, and 7687 are not currently in use on your machine.

## How to Start the Environment (Windows)

1. Extract this folder to a location on your computer.
2. Open the `.env` file in a text editor and add your OpenAI API key to the `OPENAI_API_KEY` variable (required for the RAG Chatbot to function).
3. Double-click the `start_mentor.bat` file.
   - This script will automatically trigger the docker-compose build process.
   - It will download all required images (NetBox, Neo4j, Redis, Postgres), install the Python dependencies, and ingest the included database dump (`netbox_dump.sql.gz`).
   - Note: The initial build and download may take 3 to 10 minutes depending on your internet connection.
4. Wait approximately 30 seconds after the script finishes for the databases to fully initialize.

## How to Start the Environment (Mac/Linux)

If you are not on Windows, simply open a terminal in this directory and run:
```bash
docker-compose up --build -d
```

## Accessing the Services

Once the containers are running, you can access the following services in your web browser:

### 1. NetGraphX AI Dashboard
- URL: http://localhost:8501
- Purpose: The main Streamlit dashboard containing the visual graph, AI anomaly detection, and RBAC controls.
- Default Login:
  - Username: admin
  - Password: admin123

### 2. NetBox Administration
- URL: http://localhost:8081
- Purpose: The underlying Source of Truth network database. This instance is pre-loaded with the exact data used to train the ML models.
- Default Login:
  - Username: admin
  - Password: admin

### 3. Neo4j Graph Browser
- URL: http://localhost:7474
- Purpose: The graph database containing the parsed topology nodes and edges.
- Default Login:
  - Username: neo4j
  - Password: NetGraphX123!

## Stopping the Environment

When you are finished testing, open a terminal in this directory and run:
```bash
docker-compose down
```
This will cleanly stop and remove all associated containers.
