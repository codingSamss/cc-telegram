"""Tests for authentication system."""

from datetime import datetime, timedelta

import pytest

from src.exceptions import SecurityError
from src.security.auth import AuthenticationManager, UserSession, WhitelistAuthProvider


class TestUserSession:
    """Test UserSession functionality."""

    def test_session_creation(self):
        """Test session creation."""
        session = UserSession(
            user_id=123,
            auth_provider="TestProvider",
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
        )

        assert session.user_id == 123
        assert session.auth_provider == "TestProvider"
        assert not session.is_expired()

    def test_session_expiry(self):
        """Test session expiry logic."""
        old_time = datetime.utcnow() - timedelta(hours=25)
        session = UserSession(
            user_id=123,
            auth_provider="TestProvider",
            created_at=old_time,
            last_activity=old_time,
        )

        assert session.is_expired()

    def test_session_refresh(self):
        """Test session refresh."""
        old_time = datetime.utcnow() - timedelta(hours=1)
        session = UserSession(
            user_id=123,
            auth_provider="TestProvider",
            created_at=old_time,
            last_activity=old_time,
        )

        session.refresh()
        assert not session.is_expired()
        assert session.last_activity > old_time


class TestWhitelistAuthProvider:
    """Test whitelist authentication provider."""

    async def test_allowed_user_authentication(self):
        """Test authentication of allowed user."""
        provider = WhitelistAuthProvider([123, 456])

        result = await provider.authenticate(123, {})
        assert result is True

        result = await provider.authenticate(789, {})
        assert result is False

    async def test_get_user_info(self):
        """Test user info retrieval."""
        provider = WhitelistAuthProvider([123])

        info = await provider.get_user_info(123)
        assert info is not None
        assert info["user_id"] == 123
        assert info["auth_type"] == "whitelist"

        info = await provider.get_user_info(456)
        assert info is None


class TestAuthenticationManager:
    """Test authentication manager."""

    @pytest.fixture
    def auth_manager(self):
        return AuthenticationManager([WhitelistAuthProvider([123, 456])])

    def test_manager_requires_providers(self):
        """Test that manager requires at least one provider."""
        with pytest.raises(SecurityError):
            AuthenticationManager([])

    async def test_whitelist_authentication(self, auth_manager):
        """Test authentication through whitelist."""
        result = await auth_manager.authenticate_user(123)
        assert result is True
        assert auth_manager.is_authenticated(123)

        result = await auth_manager.authenticate_user(999)
        assert result is False
        assert not auth_manager.is_authenticated(999)

    async def test_fallback_to_secondary_provider(self):
        """Test authentication checks providers in order."""
        manager = AuthenticationManager(
            [
                WhitelistAuthProvider([123]),
                WhitelistAuthProvider([789]),
            ]
        )

        result = await manager.authenticate_user(789)
        assert result is True
        assert manager.is_authenticated(789)

    async def test_session_management(self, auth_manager):
        """Test session creation and management."""
        user_id = 123

        await auth_manager.authenticate_user(user_id)

        session = auth_manager.get_session(user_id)
        assert session is not None
        assert session.user_id == user_id

        old_activity = session.last_activity
        result = auth_manager.refresh_session(user_id)
        assert result is True
        assert session.last_activity > old_activity

        auth_manager.end_session(user_id)
        assert not auth_manager.is_authenticated(user_id)

    async def test_expired_session_cleanup(self, auth_manager):
        """Test cleanup of expired sessions."""
        user_id = 123

        await auth_manager.authenticate_user(user_id)

        session = auth_manager.get_session(user_id)
        assert session is not None
        session.last_activity = datetime.utcnow() - timedelta(hours=25)

        assert not auth_manager.is_authenticated(user_id)
        assert auth_manager.get_session(user_id) is None

    async def test_session_info(self, auth_manager):
        """Test session information retrieval."""
        user_id = 123

        info = auth_manager.get_session_info(user_id)
        assert info is None

        await auth_manager.authenticate_user(user_id)
        info = auth_manager.get_session_info(user_id)

        assert info is not None
        assert info["user_id"] == user_id
        assert "created_at" in info
        assert "last_activity" in info
