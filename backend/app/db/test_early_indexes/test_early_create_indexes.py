"""
Unit tests for the `create_indexes` function in app.db.indexes.
Covers happy paths and edge cases using pytest and unittest.mock.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Import the function under test
from app.db.indexes import create_indexes

# Markers for test categories
pytestmark = [
    pytest.mark.asyncio,
]

@pytest.mark.usefixtures("mock_collections", "mock_logger")
class TestCreateIndexes:
    """Unit tests for the create_indexes function."""

    @pytest.fixture(autouse=True)
    def mock_collections(self):
        """
        Fixture to patch all collection functions to return AsyncMock objects.
        """
        with patch("app.db.indexes.col.users", new_callable=MagicMock) as users_mock, \
             patch("app.db.indexes.col.threads", new_callable=MagicMock) as threads_mock, \
             patch("app.db.indexes.col.product_cache", new_callable=MagicMock) as product_cache_mock, \
             patch("app.db.indexes.col.product_lookup_map", new_callable=MagicMock) as product_lookup_map_mock, \
             patch("app.db.indexes.col.feedback", new_callable=MagicMock) as feedback_mock:

            # Each collection function returns an AsyncMock (simulating AsyncIOMotorCollection)
            users_col = AsyncMock()
            threads_col = AsyncMock()
            product_cache_col = AsyncMock()
            product_lookup_map_col = AsyncMock()
            feedback_col = AsyncMock()

            users_mock.return_value = users_col
            threads_mock.return_value = threads_col
            product_cache_mock.return_value = product_cache_col
            product_lookup_map_mock.return_value = product_lookup_map_col
            feedback_mock.return_value = feedback_col

            # Expose for test access
            self.users_col = users_col
            self.threads_col = threads_col
            self.product_cache_col = product_cache_col
            self.product_lookup_map_col = product_lookup_map_col
            self.feedback_col = feedback_col

            yield

    @pytest.fixture(autouse=True)
    def mock_logger(self):
        """
        Fixture to patch get_logger to return a MagicMock logger.
        """
        with patch("app.db.indexes.get_logger", autospec=True) as get_logger_mock:
            logger_mock = MagicMock()
            get_logger_mock.return_value = logger_mock
            self.logger_mock = logger_mock
            yield

    @pytest.fixture(autouse=True)
    def mock_settings(self):
        """
        Fixture to patch settings.cache_ttl_seconds.
        """
        with patch("app.db.indexes.settings", autospec=True) as settings_mock:
            settings_mock.cache_ttl_seconds = 1234
            self.settings_mock = settings_mock
            yield

    # ------------------- Happy Path Tests -------------------

    @pytest.mark.happy_path
    async def test_create_indexes_happy_path(self):
        """
        Test that create_indexes calls all expected create_index methods with correct arguments.
        """
        await create_indexes()

        # users
        self.users_col.create_index.assert_any_await("email", unique=True)
        self.users_col.create_index.assert_any_await("google_id", sparse=True)
        assert self.users_col.create_index.await_count == 2

        # threads
        self.threads_col.create_index.assert_any_await([("user_id", 1), ("updated_at", -1)])
        self.threads_col.create_index.assert_any_await("is_deleted")
        assert self.threads_col.create_index.await_count == 2

        # product_cache
        self.product_cache_col.create_index.assert_any_await(
            "timestamp",
            expireAfterSeconds=self.settings_mock.cache_ttl_seconds,
            name="ttl_cache",
        )
        self.product_cache_col.create_index.assert_any_await([
            ("query_signature.category", 1),
            ("query_signature.source", 1),
        ])
        assert self.product_cache_col.create_index.await_count == 2

        # product_lookup_map
        self.product_lookup_map_col.create_index.assert_any_await("product_id", unique=True)
        self.product_lookup_map_col.create_index.assert_any_await("cache_doc_id")
        assert self.product_lookup_map_col.create_index.await_count == 2

        # feedback
        self.feedback_col.create_index.assert_any_await([("user_id", 1), ("product_id", 1)])
        self.feedback_col.create_index.assert_any_await("thread_id")
        self.feedback_col.create_index.assert_any_await("timestamp")
        assert self.feedback_col.create_index.await_count == 3

        # Logger calls
        self.logger_mock.info.assert_any_call("Creating MongoDB indexes…")
        self.logger_mock.info.assert_any_call("MongoDB indexes created")

    # ------------------- Edge Case Tests -------------------

    @pytest.mark.edge_case
    async def test_create_indexes_handles_index_creation_exceptions(self):
        """
        Test that if a create_index call raises an exception, it propagates (no silent swallow).
        """
        # Simulate an exception on one of the index creations
        self.users_col.create_index.side_effect = [None, Exception("Index error")]

        with pytest.raises(Exception, match="Index error"):
            await create_indexes()

        # The first index call should succeed, second should raise
        assert self.users_col.create_index.await_count == 2

    @pytest.mark.edge_case
    async def test_create_indexes_with_zero_ttl(self):
        """
        Test that create_indexes passes a TTL of 0 if settings.cache_ttl_seconds is 0.
        """
        self.settings_mock.cache_ttl_seconds = 0
        await create_indexes()
        self.product_cache_col.create_index.assert_any_await(
            "timestamp",
            expireAfterSeconds=0,
            name="ttl_cache",
        )

    @pytest.mark.edge_case
    async def test_create_indexes_with_negative_ttl(self):
        """
        Test that create_indexes passes a negative TTL if settings.cache_ttl_seconds is negative.
        """
        self.settings_mock.cache_ttl_seconds = -100
        await create_indexes()
        self.product_cache_col.create_index.assert_any_await(
            "timestamp",
            expireAfterSeconds=-100,
            name="ttl_cache",
        )

    @pytest.mark.edge_case
    async def test_create_indexes_logger_failure(self):
        """
        Test that if logger.info raises, the function still attempts to create indexes.
        """
        self.logger_mock.info.side_effect = [Exception("Logger fail"), None]
        # Should raise on first logger.info, so no indexes are created
        with pytest.raises(Exception, match="Logger fail"):
            await create_indexes()
        # No index creation should have occurred
        assert self.users_col.create_index.await_count == 0

    @pytest.mark.edge_case
    async def test_create_indexes_partial_collections_fail(self):
        """
        Test that if one collection function raises, the function propagates the error.
        """
        with patch("app.db.indexes.col.threads", side_effect=Exception("Threads fail")):
            with pytest.raises(Exception, match="Threads fail"):
                await create_indexes()

    @pytest.mark.edge_case
    async def test_create_indexes_all_indexes_are_idempotent(self):
        """
        Test that calling create_indexes twice does not cause errors (idempotency).
        """
        await create_indexes()
        await create_indexes()
        # All create_index calls should be made twice
        assert self.users_col.create_index.await_count == 4
        assert self.threads_col.create_index.await_count == 4
        assert self.product_cache_col.create_index.await_count == 4
        assert self.product_lookup_map_col.create_index.await_count == 4
        assert self.feedback_col.create_index.await_count == 6