"""Verify model status through the shared model-management service."""

from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.resources import get_model_service


def main() -> int:
    service = get_model_service()
    statuses = service.get_all_statuses(kind="local")

    print("Model Status")
    print("=" * 65)

    has_failure = False
    for status in statuses:
        print(f"[{status.model_id}] {status.status}")
        if status.path:
            print(f"  Path: {status.path}")
        print(f"  Detail: {status.detail}")
        print()
        has_failure = has_failure or status.status != "installed"

    print("=" * 65)
    if has_failure:
        print("WARNING: Some models are missing or incomplete!")
        print("To download models:")
        print("  uv run python scripts/install_models.py")
        print("  uv run python scripts/install_models.py --all")
        return 1

    print("All models verified successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
