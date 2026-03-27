import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Base
from app.models.user import User, UserRole

TEST_DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


async def _create_user_and_token(
    db_session: AsyncSession, role: str
) -> str:
    """Create a real User row in the DB and return a valid JWT for it."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"{role}_{user_id.hex[:8]}@test.com",
        hashed_password=_hash_password("testpass"),
        role=UserRole(role),
    )
    db_session.add(user)
    await db_session.flush()

    payload = {
        "sub": str(user_id),
        "email": user.email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def make_token(role: str = "admin", user_id: str | None = None) -> str:
    """Create a JWT token (without DB user). Use role-specific fixtures instead."""
    uid = user_id or str(uuid.uuid4())
    payload = {
        "sub": uid,
        "email": f"{role}@test.com",
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession) -> str:
    return await _create_user_and_token(db_session, "admin")


@pytest_asyncio.fixture
async def compliance_manager_token(db_session: AsyncSession) -> str:
    return await _create_user_and_token(db_session, "compliance_manager")


@pytest_asyncio.fixture
async def devops_token(db_session: AsyncSession) -> str:
    return await _create_user_and_token(db_session, "devops_engineer")


@pytest_asyncio.fixture
async def developer_token(db_session: AsyncSession) -> str:
    return await _create_user_and_token(db_session, "developer")


@pytest_asyncio.fixture
async def auditor_token(db_session: AsyncSession) -> str:
    return await _create_user_and_token(db_session, "auditor")
