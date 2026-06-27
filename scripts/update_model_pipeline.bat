@echo off
REM ==============================================================================
REM   NetGraphX - UPDATE MODEL PIPELINE
REM ==============================================================================
REM   This script is for Data & AI Engineering purposes ONLY.
REM   Do not run this for daily operation. Use `start.bat` for daily operation.
REM
REM   This script executes a one-time sequence to:
REM     1. Wipe the current mock data and inject a massive new synthetic topology.
REM     2. Extract graph features from NetBox into rogue_features.csv.
REM     3. Train the AI model using GroupKFold and save rogue_model.pkl.
REM     4. Rebuild the Neo4j graph and embeddings.
REM     5. Run the inference pipeline to update Neo4j with AI Predictions.
REM ==============================================================================
echo.

echo Installing dependencies...
.\.venv\Scripts\python.exe -m pip install joblib

echo.
set PYTHONPATH=.

echo [1/5] Injecting Mock Data...
.\.venv\Scripts\python.exe -m data.mock.mock_data_inject

echo.
echo [2/5] Extracting Features...
.\.venv\Scripts\python.exe -m src.data_pipeline.extract_features

echo.
echo [3/5] Training Model...
.\.venv\Scripts\python.exe -m src.data_pipeline.train

echo.
echo [4/5] Running Graph Engine (fetching topology and updating Neo4j)...
.\.venv\Scripts\python.exe main.py --run-engine

echo.
echo [5/5] Predicting Rogues ^& Updating Neo4j...
.\.venv\Scripts\python.exe -m src.data_pipeline.predict

echo.
echo ==============================================================================
echo   Update Model Pipeline complete.
echo ==============================================================================
