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
echo ==================================================
echo   SUCCESS! The environment is spinning up.
echo ==================================================
echo.
echo It takes about 30 seconds for all databases to initialize.
echo Once ready, you can access the following services in your browser:
echo.
echo 1. NetGraphX AI Dashboard : http://localhost:8501
echo 2. NetBox Administration  : http://localhost:8081 (admin/admin)
echo 3. Neo4j Graph Browser    : http://localhost:7474 (neo4j/NetGraphX123!)
echo.
echo To stop everything later, run: docker-compose down
echo ==================================================
pause
