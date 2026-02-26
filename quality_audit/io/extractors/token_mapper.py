"""
Token-to-cell mapping module.
Maps OCR tokens to detected cell boxes using geometric overlap.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ocr import OCRToken
from .structure import CellBox

logger = logging.getLogger(__name__)


@dataclass
class CellContent:
    """Aggregated content for a single cell."""

    row: int
    col: int
    text: str
    confidence: float  # mean of token confidences
    token_count: int
    raw_tokens: List[OCRToken] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class TokenToCellMapper:
    """
    Maps OCR tokens to detected cells using geometric overlap.

    Uses IoU (Intersection over Union) or containment to assign
    tokens to cells, then aggregates tokens per cell.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        containment_threshold: float = 0.7,
        use_center_point: bool = True,
    ):
        """
        Initialize the token mapper.

        Args:
            iou_threshold: Minimum IoU for token-cell assignment.
            containment_threshold: Minimum containment ratio for assignment.
            use_center_point: If True, primarily use center point containment.
        """
        self.iou_threshold = iou_threshold
        self.containment_threshold = containment_threshold
        self.use_center_point = use_center_point

    def map_tokens_to_cells(
        self,
        tokens: List[OCRToken],
        cells: List[CellBox],
    ) -> Dict[Tuple[int, int], CellContent]:
        """
        Map tokens to cells based on geometric overlap.

        Args:
            tokens: List of OCR tokens with bounding boxes.
            cells: List of detected cell boxes.

        Returns:
            Dict mapping (row, col) to CellContent.
        """
        if not cells:
            return {}

        # Initialize cell contents
        cell_tokens: Dict[Tuple[int, int], List[OCRToken]] = {}
        for cell in cells:
            cell_tokens[(cell.row, cell.col)] = []

        # Sort tokens by reading order (top-to-bottom, left-to-right)
        sorted_tokens = sorted(
            tokens,
            key=lambda t: (t.y1, t.x1),
        )

        # Map each token to best matching cell
        unassigned_count = 0
        for token in sorted_tokens:
            best_cell = self._find_best_cell(token, cells)
            if best_cell is not None:
                cell_tokens[(best_cell.row, best_cell.col)].append(token)
            else:
                unassigned_count += 1
                logger.debug(
                    "Token '%s' at (%d,%d) not assigned to any cell",
                    token.text[:20] if token.text else "",
                    token.x1,
                    token.y1,
                )

        if unassigned_count > 0:
            logger.info(
                "Token mapping: %d tokens unassigned out of %d",
                unassigned_count,
                len(tokens),
            )

        # Aggregate tokens per cell
        result = {}
        for (row, col), tokens_in_cell in cell_tokens.items():
            content = self._aggregate_tokens(row, col, tokens_in_cell)
            result[(row, col)] = content

        return result

    def _find_best_cell(
        self, token: OCRToken, cells: List[CellBox]
    ) -> Optional[CellBox]:
        """Find the best matching cell for a token."""
        best_cell = None
        best_score = 0.0

        for cell in cells:
            score = self._compute_match_score(token, cell)
            if score > best_score:
                best_score = score
                best_cell = cell

        # Check if best score meets threshold
        if self.use_center_point:
            if best_cell and self._is_center_contained(token, best_cell):
                return best_cell
        else:
            if best_score >= self.iou_threshold:
                return best_cell

        return None

    def _compute_match_score(self, token: OCRToken, cell: CellBox) -> float:
        """Compute match score between token and cell."""
        # IoU calculation
        iou = self._compute_iou(
            (token.x1, token.y1, token.x2, token.y2),
            (cell.x1, cell.y1, cell.x2, cell.y2),
        )

        # Containment (how much of token is inside cell)
        containment = self._compute_containment(
            (token.x1, token.y1, token.x2, token.y2),
            (cell.x1, cell.y1, cell.x2, cell.y2),
        )

        # Weighted combination
        return max(iou, containment * 0.8)

    def _compute_iou(
        self,
        box1: Tuple[int, int, int, int],
        box2: Tuple[int, int, int, int],
    ) -> float:
        """Compute Intersection over Union between two boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    def _compute_containment(
        self,
        inner: Tuple[int, int, int, int],
        outer: Tuple[int, int, int, int],
    ) -> float:
        """Compute how much of inner box is contained in outer box."""
        x1 = max(inner[0], outer[0])
        y1 = max(inner[1], outer[1])
        x2 = min(inner[2], outer[2])
        y2 = min(inner[3], outer[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        inner_area = (inner[2] - inner[0]) * (inner[3] - inner[1])

        if inner_area <= 0:
            return 0.0

        return intersection / inner_area

    def _is_center_contained(self, token: OCRToken, cell: CellBox) -> bool:
        """Check if token center point is inside cell."""
        cx, cy = token.center
        return bool(cell.x1 <= cx <= cell.x2 and cell.y1 <= cy <= cell.y2)

    def _aggregate_tokens(
        self, row: int, col: int, tokens: List[OCRToken]
    ) -> CellContent:
        """Aggregate tokens into a single cell content."""
        if not tokens:
            return CellContent(
                row=row,
                col=col,
                text="",
                confidence=0.0,
                token_count=0,
                raw_tokens=[],
            )

        # Sort tokens by reading order within cell
        sorted_tokens = sorted(tokens, key=lambda t: (t.y1, t.x1))

        # Concatenate text with space separators
        # Group tokens by approximate line (using y-position clustering)
        lines = self._group_tokens_by_line(sorted_tokens)
        text_parts = []
        for line in lines:
            line_text = " ".join(t.text for t in line)
            text_parts.append(line_text)
        text = " ".join(text_parts)

        # Compute mean confidence
        confidences = [t.confidence for t in tokens]
        mean_confidence = sum(confidences) / len(confidences)

        return CellContent(
            row=row,
            col=col,
            text=text.strip(),
            confidence=mean_confidence,
            token_count=len(tokens),
            raw_tokens=sorted_tokens,
        )

    def _group_tokens_by_line(
        self, tokens: List[OCRToken], line_threshold: int = 10
    ) -> List[List[OCRToken]]:
        """Group tokens into lines based on y-position."""
        if not tokens:
            return []

        lines = []
        current_line = [tokens[0]]
        current_y = tokens[0].y1

        for token in tokens[1:]:
            # If y-position is close to current line, add to same line
            if abs(token.y1 - current_y) <= line_threshold:
                current_line.append(token)
            else:
                # Sort current line by x position
                lines.append(sorted(current_line, key=lambda t: t.x1))
                current_line = [token]
                current_y = token.y1

        if current_line:
            lines.append(sorted(current_line, key=lambda t: t.x1))

        return lines


def build_grid_from_cell_contents(
    cell_contents: Dict[Tuple[int, int], CellContent],
    num_rows: int,
    num_cols: int,
) -> List[List[str]]:
    """
    Build a 2D grid from cell contents.

    Args:
        cell_contents: Dict mapping (row, col) to CellContent.
        num_rows: Number of rows in the grid.
        num_cols: Number of columns in the grid.

    Returns:
        2D list of strings representing the table.
    """
    grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]

    for (row, col), content in cell_contents.items():
        if 0 <= row < num_rows and 0 <= col < num_cols:
            grid[row][col] = content.text

    return grid
