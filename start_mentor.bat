@echo off
title NetGraphX - Mentor Local Environment

echo ==================================================
echo   NetGraphX - Setting up your local environment...
echo ==================================================
echo.
echo Please wait while we download the required Docker images, build
echo the application, and load the pre-configured NetBox database.
echo This might take a few minutes the first time you run it!
echo.

REM Start the docker-compose stack and detach
docker-compose up --build -d

echo.
echo Waiting 30 seconds for databases to initialize before populating Neo4j...
timeout /t 30 /nobreak > nul

echo.
echo Populating Neo4j Knowledge Graph from NetBox...
docker exec netgraphx-app python main.py --run-engine

echo.
echo ==================================================
echo   SUCCESS! The environment is ready.
echo ==================================================
echo.
echo Once ready, you can access the following services in your browser:
echo.
echo 1. NetGraphX AI Dashboard : http://localhost:8501 (admin/admin123)
echo 2. NetBox Administration  : http://localhost:8081 (admin/admin)
echo 3. Neo4j Graph Browser    : http://localhost:7474 (neo4j/huyngo1234)
echo.
echo To stop everything later, run: docker-compose down
echo ==================================================
pause
