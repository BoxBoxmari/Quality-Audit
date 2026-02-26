from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class TaxRateConfig:
    """Configuration for tax rate resolution."""

    mode: str  # "prompt", "all", "individual"
    all_rate: Optional[float] = None  # Used when mode="all"
    map_path: Optional[Path] = None  # Path to JSON map file
    map_data: Optional[Dict[str, float]] = None  # Loaded JSON map
    default_rate: float = 0.25  # Fallback rate

    def resolve_rate(self, file_path: Path, base_path: Path) -> Optional[float]:
        """
        Resolve tax rate based on configuration mode.

        Args:
            file_path: Path to the current file being processed
            base_path: Base path for resolving relative paths

        Returns:
            Resolved tax rate (0.0-1.0) or None if prompt mode should be used
        """
        if self.mode == "all":
            return self.all_rate

        if self.mode == "individual":
            if not self.map_data:
                return self.default_rate

            # normalization
            try:
                rel_path = file_path.relative_to(base_path).as_posix()
            except ValueError:
                rel_path = file_path.name

            # Try exact relative path first
            if rel_path in self.map_data:
                return self.map_data[rel_path]

            # Try basename
            if file_path.name in self.map_data:
                return self.map_data[file_path.name]

            # Fallback to default in map or global default
            return self.map_data.get("default", self.default_rate)

        # mode == "prompt"
        return None
