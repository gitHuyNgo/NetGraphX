@echo off
REM ==============================================================================
REM   NetGraphX - UI TESTING MOCK PIPELINE
REM ==============================================================================
REM   Run this script to inject a smaller k=6 graph (~250 devices) with exactly:
REM   - 2 Loops
REM   - 3 VLAN Mismatches
REM   - 2 Rogue Devices
REM
REM   This proves Zero-Shot Transfer: We use the existing massive-scale .pkl
REM   model to predict anomalies on this much smaller topology without retraining!
REM ==============================================================================
echo.

set PYTHONPATH=.

echo [1/4] Injecting k=6 UI Mock Data...
.\.venv\Scripts\python.exe -m data.mock.mock_data_ui

echo.
echo [2/4] Extracting Features from NetBox...
.\.venv\Scripts\python.exe -m src.data_pipeline.extract_features

echo.
echo [3/4] Running Graph Engine (Building Neo4j topology)...
.\.venv\Scripts\python.exe main.py --run-engine

echo.
echo [4/4] Zero-Shot Inference: Predicting Rogues (using existing model)...
.\.venv\Scripts\python.exe -m src.data_pipeline.predict

echo.
echo ==============================================================================
echo   UI Testing Pipeline complete. You can now view the dashboard!
echo ==============================================================================
pause
