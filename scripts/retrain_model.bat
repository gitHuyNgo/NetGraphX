@echo off
REM ==============================================================================
REM   NetGraphX - ACTIVE LEARNING (RETRAIN) PIPELINE
REM ==============================================================================
REM   Run this script to Retrain the model on human feedback.
REM   Unlike `update_model_pipeline.bat`, this DOES NOT wipe the mock data,
REM   preserving your Human-in-the-Loop accept/reject clicks!
REM ==============================================================================
echo.

set PYTHONPATH=.

echo [1/3] Extracting Features and Human Feedback from Neo4j...
.\.venv\Scripts\python.exe -m src.data_pipeline.extract_features

echo.
echo [2/3] Active Learning: Retraining Supervised Model on Feedback...
.\.venv\Scripts\python.exe -m src.data_pipeline.train

echo.
echo [3/3] Predicting Rogues ^& Updating Graph...
.\.venv\Scripts\python.exe -m src.data_pipeline.predict

echo.
echo ==============================================================================
echo   Active Learning Retrain complete! Model is now smarter.
echo ==============================================================================
pause
