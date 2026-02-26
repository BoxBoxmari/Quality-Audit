"""
Base service class for service layer abstraction.
"""

from typing import Optional

from ..core.cache_manager import AuditContext, LRUCacheManager


class BaseService:
    """
    Base class for all services in the Quality Audit application.

    Provides common functionality and ensures consistent service patterns
    across the application.
    """

    def __init__(
        self,
        context: Optional[AuditContext] = None,
        cache_manager: Optional[LRUCacheManager] = None,
    ):
        """
        Initialize base service.

        Args:
            context: Audit context (preferred)
            cache_manager: Cache manager for backward compatibility
        """
        if context:
            self.context = context
        else:
            cache = cache_manager or LRUCacheManager()
            self.context = AuditContext(cache=cache)

    def clear_context(self) -> None:
        """Clear the audit context."""
        self.context.clear()
