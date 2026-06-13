"""Smoke tests da infra de integração — seed idempotente e rollback transacional."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.seed import (
    SEED_TABULACAO_CODIGOS,
    seed_default_admin,
    seed_default_tabulacoes,
)
from app.core.security import hash_password
from app.models.tabulacao import Tabulacao
from app.models.user import User

pytestmark = pytest.mark.integration


async def test_seed_default_tabulacoes_is_idempotent(db_session) -> None:
    await seed_default_admin(db_session)
    await seed_default_tabulacoes(db_session)

    count_first = await db_session.scalar(select(func.count()).select_from(Tabulacao))

    await seed_default_tabulacoes(db_session)

    count_second = await db_session.scalar(select(func.count()).select_from(Tabulacao))

    assert count_first == count_second
    assert count_first == len(SEED_TABULACAO_CODIGOS)

    neg_rows = await db_session.scalars(
        select(Tabulacao.codigo).where(
            Tabulacao.is_system.is_(True),
            Tabulacao.codigo.like("NEG:%"),
        )
    )
    sip_rows = await db_session.scalars(
        select(Tabulacao.codigo).where(
            Tabulacao.is_system.is_(True),
            Tabulacao.codigo.like("SIP:%"),
        )
    )
    assert len(neg_rows.all()) >= 1
    assert len(sip_rows.all()) >= 1


async def test_session_flush_visible_within_transaction(db_session) -> None:
    user = User(
        email="rollback-test@example.com",
        hashed_password=hash_password("secret"),
        full_name="Rollback Test",
    )
    db_session.add(user)
    await db_session.flush()

    found = await db_session.scalar(
        select(User).where(User.email == "rollback-test@example.com")
    )
    assert found is not None
    assert found.full_name == "Rollback Test"


async def test_rollback_clears_prior_test_data(db_session) -> None:
    """Registro criado no teste anterior não deve existir após rollback."""
    found = await db_session.scalar(
        select(User).where(User.email == "rollback-test@example.com")
    )
    assert found is None
