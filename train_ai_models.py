"""CLI entry point for the multi-domain Isolation Forest training pipeline."""
from backend.ml.training import train_all

if __name__ == "__main__":
    generated = train_all()
    print(f"Trained {len(generated)} Isolation Forest models")
