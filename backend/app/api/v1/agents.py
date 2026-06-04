"""Agent CRUD API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import raise_if_cannot_delete, raise_if_cannot_edit, raise_if_cannot_view
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])


async def _get_agent(
    agent_id: uuid.UUID, user: User, db: AsyncSession
) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    raise_if_cannot_view(agent, user, not_found_detail="Agent not found")
    return agent


@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Agent]:
    result = await db.execute(
        select(Agent).where(or_(Agent.is_system.is_(True), Agent.user_id == user.id))
    )
    return list(result.scalars().all())


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = Agent(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        mode=payload.mode,
        config=payload.config,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    return await _get_agent(agent_id, user, db)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    agent = await _get_agent(agent_id, user, db)
    raise_if_cannot_edit(agent, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    agent = await _get_agent(agent_id, user, db)
    raise_if_cannot_delete(agent, user)
    await db.delete(agent)
    await db.commit()
