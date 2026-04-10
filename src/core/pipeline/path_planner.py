"""Output path planning for pipeline artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.utils import ensure_dir

if TYPE_CHECKING:
    from . import PipelineConfig


class PathPlanner:
    """Resolve output paths for single and batch modes."""

    def __init__(self, config: "PipelineConfig"):
        self.config = config

    def resolve_output_dirs(self) -> tuple[Path, Path, str]:
        """Return (mix_path, by_product_dir, task_name)."""
        config = self.config
        input_path = Path(config.input_path)
        task_name = input_path.stem
        input_ext = input_path.suffix

        if config.output_mode == "batch" and config.batch_root_dir:
            root_dir = Path(config.batch_root_dir)
            main_product_dir = root_dir / "Main_Product"
            by_product_dir = root_dir / "BY_Product" / f"{task_name}_by"
        else:
            if config.output_dir:
                base_dir = Path(config.output_dir)
            else:
                base_dir = input_path.parent / f"{task_name}_output"
            main_product_dir = base_dir
            by_product_dir = base_dir / "BY_Product"

        mix_path = main_product_dir / f"{task_name}_mix{input_ext}"

        ensure_dir(main_product_dir)
        ensure_dir(by_product_dir)
        return mix_path, by_product_dir, task_name
