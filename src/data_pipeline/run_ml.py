import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("\n[Step 5] Running ML Anomaly Detection (DOMINANT) in background...")
    try:
        subprocess.run([sys.executable, "-m", "src.data_pipeline.extract_features"], check=True)
        subprocess.run([sys.executable, "-m", "src.data_pipeline.predict"], check=True)
        logger.info("[ML] Anomaly detection completed.")
    except subprocess.CalledProcessError as e:
        logger.error(f"[ML] Anomaly detection failed with code {e.returncode}")

if __name__ == "__main__":
    main()
