"""Fine-tune YOLO11 on your game screenshots (humanoid enemies, class 0).

Usage:
    python training/train.py            # yolo11n, 100 epochs
    python training/train.py --size s   # yolo11s (more accurate, slower)
    python training/train.py --epochs 50 --batch 32

Needs: pip install ultralytics (already in this project).
GPU: uses CUDA device 0 (your RTX 3090, 24 GB -> batch 16-32 fits easily).

After training, best weights land in runs/detect/game_*/weights/best.pt.
To use them: back up models/yolo11n.pt, copy best.pt over it, and delete
models/yolo11n_<imgsz>.engine so a fresh TensorRT engine is exported.
"""
import argparse
import os
import shutil

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="n", choices=["n", "s"],
                    help="yolo11n (fast) or yolo11s (accurate)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--imgsz", type=int, default=640,
                    help="match inference imgsz in config (320/416/640)")
    ap.add_argument("--data", default=os.path.join(PROJECT_ROOT, "training", "game.yaml"))
    args = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(os.path.join(PROJECT_ROOT, "models", f"yolo11{args.size}.pt"))
    model.train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=0,
        patience=20,          # early stop if no improvement for 20 epochs
        name="game_finetune",
        exist_ok=False,
    )

    # Report where best.pt went.
    print("\nDone. Check runs/detect/game_finetune*/weights/best.pt")


if __name__ == "__main__":
    main()
