"""
Baseline grid detector using OpenCV line detection and projection profiles.
Falls back to simple clustering when line detection fails.
"""

import logging
from typing import List, Tuple

import numpy as np

from .base import CellBox, StructureResult, TableStructureRecognizer

try:
    import cv2

    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


logger = logging.getLogger(__name__)


class BaselineGridRecognizer(TableStructureRecognizer):
    """
    Simple table structure recognizer using line detection and projection profiles.

    This is the P0 fallback that requires no ML models.
    Uses OpenCV to detect horizontal and vertical lines, then clusters them
    into row and column boundaries.
    """

    def __init__(
        self,
        line_threshold: int = 50,
        min_line_ratio: float = 0.3,
        cluster_threshold: int = 10,
    ):
        """
        Initialize the baseline grid recognizer.

        Args:
            line_threshold: Minimum length for detected lines.
            min_line_ratio: Minimum ratio of line length to image dimension.
            cluster_threshold: Pixel distance for clustering similar line positions.
        """
        self.line_threshold = line_threshold
        self.min_line_ratio = min_line_ratio
        self.cluster_threshold = cluster_threshold

    @property
    def recognizer_type(self) -> str:
        return "baseline_grid"

    def detect_cells(self, image: np.ndarray) -> StructureResult:
        """
        Detect table cells using line detection and projection profiles.

        Args:
            image: RGB numpy array of the table image.

        Returns:
            StructureResult with detected cells.
        """
        if not HAS_CV2:
            return StructureResult(
                recognizer_type=self.recognizer_type,
                error="OpenCV not available",
            )

        if image is None or image.size == 0:
            return StructureResult(
                recognizer_type=self.recognizer_type,
                error="Empty image",
            )

        try:
            # Convert to grayscale
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            else:
                gray = image.copy()

            h, w = gray.shape

            # Try line-based detection first
            row_bounds, col_bounds = self._detect_lines(gray)

            # Fall back to projection profile if line detection fails
            if len(row_bounds) < 2 or len(col_bounds) < 2:
                logger.debug("Line detection failed, using projection profiles")
                row_bounds, col_bounds = self._detect_from_projection(gray)

            # If still not enough lines, use simple grid
            if len(row_bounds) < 2 or len(col_bounds) < 2:
                logger.debug("Projection failed, using simple grid estimation")
                row_bounds, col_bounds = self._estimate_simple_grid(gray)

            if len(row_bounds) < 2 or len(col_bounds) < 2:
                return StructureResult(
                    recognizer_type=self.recognizer_type,
                    error="Could not detect grid structure",
                )

            # Build cells from row and column boundaries
            cells = self._build_cells(row_bounds, col_bounds)

            num_rows = len(row_bounds) - 1
            num_cols = len(col_bounds) - 1

            return StructureResult(
                cells=cells,
                num_rows=num_rows,
                num_cols=num_cols,
                recognizer_type=self.recognizer_type,
                confidence=0.7,  # Baseline confidence
            )

        except Exception as e:
            logger.warning("Baseline grid detection failed: %s", e)
            return StructureResult(
                recognizer_type=self.recognizer_type,
                error=str(e),
            )

    def _detect_lines(self, gray: np.ndarray) -> Tuple[List[int], List[int]]:
        """Detect horizontal and vertical lines using Hough transform."""
        h, w = gray.shape

        # Edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)

        # Dilate to connect nearby edges
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        # Detect lines using probabilistic Hough transform
        min_line_length = int(min(w, h) * self.min_line_ratio)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=self.line_threshold,
            minLineLength=min_line_length,
            maxLineGap=10,
        )

        horizontal_lines = []
        vertical_lines = []

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)

                # Horizontal lines (angle near 0 or 180)
                if angle < 10 or angle > 170:
                    y_mid = (y1 + y2) // 2
                    horizontal_lines.append(y_mid)

                # Vertical lines (angle near 90)
                elif 80 < angle < 100:
                    x_mid = (x1 + x2) // 2
                    vertical_lines.append(x_mid)

        # Cluster nearby lines
        row_bounds = self._cluster_positions(horizontal_lines, [0, h])
        col_bounds = self._cluster_positions(vertical_lines, [0, w])

        return row_bounds, col_bounds

    def _detect_from_projection(self, gray: np.ndarray) -> Tuple[List[int], List[int]]:
        """Detect grid from projection profiles (dark horizontal/vertical bands)."""
        h, w = gray.shape

        # Invert so dark lines become peaks
        inverted = 255 - gray

        # Horizontal projection (sum along rows to find horizontal lines)
        h_proj = np.mean(inverted, axis=1)
        row_peaks = self._find_peaks(h_proj, min_distance=10)
        row_bounds = [0] + list(row_peaks) + [h]

        # Vertical projection (sum along columns to find vertical lines)
        v_proj = np.mean(inverted, axis=0)
        col_peaks = self._find_peaks(v_proj, min_distance=10)
        col_bounds = [0] + list(col_peaks) + [w]

        return row_bounds, col_bounds

    def _estimate_simple_grid(self, gray: np.ndarray) -> Tuple[List[int], List[int]]:
        """
        Estimate a simple uniform grid based on content analysis.
        Used as last resort when line detection fails.
        """
        h, w = gray.shape

        # Find content regions using thresholding
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

        # Find contours to estimate number of text blocks
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if len(contours) < 2:
            # Can't estimate grid
            return [], []

        # Get bounding boxes of contours
        boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 50]

        if len(boxes) < 2:
            return [], []

        # Cluster y positions to estimate rows
        y_centers = sorted([y + h // 2 for x, y, w, h in boxes])
        row_bounds = self._cluster_to_boundaries(y_centers, h)

        # Cluster x positions to estimate columns
        x_centers = sorted([x + w // 2 for x, y, w, h in boxes])
        col_bounds = self._cluster_to_boundaries(x_centers, w)

        return row_bounds, col_bounds

    def _cluster_positions(
        self, positions: List[int], boundaries: List[int]
    ) -> List[int]:
        """Cluster nearby positions and add boundaries."""
        if not positions:
            return boundaries

        positions = sorted(positions)
        clustered = [boundaries[0]]

        for pos in positions:
            # Skip if too close to last cluster center
            if abs(pos - clustered[-1]) > self.cluster_threshold:
                clustered.append(pos)

        # Ensure end boundary is included
        if abs(clustered[-1] - boundaries[-1]) > self.cluster_threshold:
            clustered.append(boundaries[-1])

        return sorted(set(clustered))

    def _cluster_to_boundaries(self, centers: List[int], max_val: int) -> List[int]:
        """Convert center points to cell boundaries."""
        if len(centers) < 2:
            return [0, max_val]

        # Cluster centers
        clusters = []
        current_cluster = [centers[0]]

        for c in centers[1:]:
            if c - current_cluster[-1] < self.cluster_threshold * 2:
                current_cluster.append(c)
            else:
                clusters.append(sum(current_cluster) // len(current_cluster))
                current_cluster = [c]

        if current_cluster:
            clusters.append(sum(current_cluster) // len(current_cluster))

        # Convert to boundaries (midpoints between clusters)
        boundaries = [0]
        for i in range(len(clusters) - 1):
            boundaries.append((clusters[i] + clusters[i + 1]) // 2)
        boundaries.append(max_val)

        return boundaries

    def _find_peaks(self, projection: np.ndarray, min_distance: int = 10) -> List[int]:
        """Find peaks in a projection profile indicating lines."""
        if len(projection) == 0:
            return []

        # Smooth the projection
        kernel_size = 5
        smoothed = np.convolve(
            projection, np.ones(kernel_size) / kernel_size, mode="same"
        )

        # Find local maxima
        peaks: List[int] = []
        threshold = np.mean(smoothed) + np.std(smoothed) * 0.5

        for i in range(1, len(smoothed) - 1):
            if (
                smoothed[i] > threshold
                and smoothed[i] > smoothed[i - 1]
                and smoothed[i] > smoothed[i + 1]
                and (not peaks or (i - peaks[-1]) >= min_distance)
            ):
                peaks.append(i)

        return peaks

    def _build_cells(
        self, row_bounds: List[int], col_bounds: List[int]
    ) -> List[CellBox]:
        """Build cell boxes from row and column boundaries."""
        cells = []

        for r in range(len(row_bounds) - 1):
            for c in range(len(col_bounds) - 1):
                cell = CellBox(
                    row=r,
                    col=c,
                    x1=col_bounds[c],
                    y1=row_bounds[r],
                    x2=col_bounds[c + 1],
                    y2=row_bounds[r + 1],
                )
                cells.append(cell)

        return cells
