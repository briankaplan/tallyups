#!/usr/bin/env python3
"""
Thread-Safe Cache Manager for ReceiptAI
========================================
Provides thread-safe caching for DataFrame and other shared resources.

Features:
- Thread-safe read/write with RLock
- TTL-based cache expiration
- Atomic updates
- Context manager support
"""

import threading
import time
from typing import Any, Optional, Callable, TypeVar
from functools import wraps
import pandas as pd

T = TypeVar('T')


class ThreadSafeCache:
    """
    Generic thread-safe cache with TTL support.

    Usage:
        cache = ThreadSafeCache(ttl_seconds=300)
        cache.set('key', value)
        value = cache.get('key')
    """

    def __init__(self, ttl_seconds: int = 300):
        self._lock = threading.RLock()
        self._data: dict = {}
        self._timestamps: dict = {}
        self._ttl = ttl_seconds

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache, returning default if expired or missing."""
        with self._lock:
            if key not in self._data:
                return default

            # Check TTL
            if self._is_expired(key):
                del self._data[key]
                del self._timestamps[key]
                return default

            return self._data[key]

    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp."""
        with self._lock:
            self._data[key] = value
            self._timestamps[key] = time.time()

    def delete(self, key: str) -> bool:
        """Delete key from cache. Returns True if key existed."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                del self._timestamps[key]
                return True
            return False

    def invalidate(self, key: str = None) -> None:
        """Invalidate specific key or all keys if key is None."""
        with self._lock:
            if key is None:
                self._data.clear()
                self._timestamps.clear()
            elif key in self._timestamps:
                # Set timestamp to 0 to force expiration
                self._timestamps[key] = 0

    def _is_expired(self, key: str) -> bool:
        """Check if key has expired based on TTL."""
        if key not in self._timestamps:
            return True
        age = time.time() - self._timestamps[key]
        return age >= self._ttl

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        """
        Get value from cache, or compute and cache it if missing/expired.

        Args:
            key: Cache key
            factory: Callable that returns the value to cache

        Returns:
            Cached or freshly computed value
        """
        with self._lock:
            value = self.get(key)
            if value is None:
                value = factory()
                self.set(key, value)
            return value


class DataFrameCache:
    """
    Thread-safe cache specifically for pandas DataFrames.

    Provides atomic read/write operations and prevents race conditions
    when multiple threads access the transaction DataFrame.

    Usage:
        df_cache = DataFrameCache(ttl_seconds=300)

        # Thread-safe read
        df = df_cache.get_dataframe()

        # Thread-safe update
        with df_cache.write_lock():
            df = df_cache.get_dataframe_unsafe()
            # modify df
            df_cache.set_dataframe(df)
    """

    def __init__(self, ttl_seconds: int = 300):
        self._lock = threading.RLock()
        self._df: Optional[pd.DataFrame] = None
        self._timestamp: Optional[float] = None
        self._ttl = ttl_seconds
        self._load_in_progress = False

    @property
    def is_valid(self) -> bool:
        """Check if cache has valid, non-expired data."""
        with self._lock:
            if self._df is None or self._timestamp is None:
                return False
            age = time.time() - self._timestamp
            return age < self._ttl

    def get_dataframe(self, loader: Callable[[], pd.DataFrame] = None) -> Optional[pd.DataFrame]:
        """
        Get DataFrame from cache, optionally loading if expired.

        Args:
            loader: Optional callable to load data if cache is invalid

        Returns:
            DataFrame copy (thread-safe) or None if no data
        """
        with self._lock:
            # Check if cache is valid
            if self.is_valid and self._df is not None:
                return self._df.copy()

            # Cache invalid - try to load if loader provided
            if loader is not None and not self._load_in_progress:
                self._load_in_progress = True
                try:
                    new_df = loader()
                    self._df = new_df
                    self._timestamp = time.time()
                    return self._df.copy()
                finally:
                    self._load_in_progress = False

            # Return existing data even if expired (better than nothing)
            if self._df is not None:
                return self._df.copy()

            return None

    def get_dataframe_unsafe(self) -> Optional[pd.DataFrame]:
        """
        Get DataFrame reference without copying (use within write_lock only).

        WARNING: Only use this within a write_lock() context manager!
        """
        return self._df

    def set_dataframe(self, df: pd.DataFrame) -> None:
        """Set DataFrame in cache (thread-safe)."""
        with self._lock:
            self._df = df
            self._timestamp = time.time()

    def invalidate(self) -> None:
        """Invalidate cache, forcing reload on next access."""
        with self._lock:
            self._timestamp = None

    def write_lock(self):
        """
        Context manager for write operations.

        Usage:
            with df_cache.write_lock():
                df = df_cache.get_dataframe_unsafe()
                # modify df
                df_cache.set_dataframe(df)
        """
        return self._lock

    def update_row(self, index_col: str, index_val: Any, updates: dict) -> bool:
        """
        Thread-safe row update.

        Args:
            index_col: Column name to match (e.g., '_index')
            index_val: Value to match in index column
            updates: Dictionary of column -> new value

        Returns:
            True if row was found and updated
        """
        with self._lock:
            if self._df is None:
                return False

            mask = self._df[index_col] == index_val
            if not mask.any():
                return False

            for col, val in updates.items():
                if col in self._df.columns:
                    self._df.loc[mask, col] = val

            return True

    def get_row(self, index_col: str, index_val: Any) -> Optional[dict]:
        """
        Thread-safe row retrieval.

        Args:
            index_col: Column name to match
            index_val: Value to match

        Returns:
            Row as dictionary or None if not found
        """
        with self._lock:
            if self._df is None:
                return None

            mask = self._df[index_col] == index_val
            if not mask.any():
                return None

            return self._df.loc[mask].iloc[0].to_dict()

    def append_row(self, row_data: dict) -> None:
        """Thread-safe row append."""
        with self._lock:
            if self._df is None:
                self._df = pd.DataFrame([row_data])
            else:
                self._df = pd.concat([self._df, pd.DataFrame([row_data])], ignore_index=True)
            self._timestamp = time.time()


# Global instances
_df_cache: Optional[DataFrameCache] = None
_receipt_meta_cache: Optional[ThreadSafeCache] = None


def get_df_cache() -> DataFrameCache:
    """Get the global DataFrame cache instance."""
    global _df_cache
    if _df_cache is None:
        _df_cache = DataFrameCache(ttl_seconds=300)
    return _df_cache


def get_receipt_meta_cache() -> ThreadSafeCache:
    """Get the global receipt metadata cache instance."""
    global _receipt_meta_cache
    if _receipt_meta_cache is None:
        _receipt_meta_cache = ThreadSafeCache(ttl_seconds=600)
    return _receipt_meta_cache


def cached(cache_key: str, ttl_seconds: int = 300):
    """
    Decorator for caching function results.

    Usage:
        @cached('my_expensive_function', ttl_seconds=60)
        def my_expensive_function():
            return expensive_computation()
    """
    _cache = ThreadSafeCache(ttl_seconds=ttl_seconds)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Create cache key from function args
            key = f"{cache_key}:{hash(str(args) + str(sorted(kwargs.items())))}"

            result = _cache.get(key)
            if result is not None:
                return result

            result = func(*args, **kwargs)
            _cache.set(key, result)
            return result

        # Expose cache invalidation
        wrapper.invalidate = lambda: _cache.invalidate()
        return wrapper

    return decorator
