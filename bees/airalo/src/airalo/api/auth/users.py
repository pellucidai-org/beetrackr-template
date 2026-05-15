"""FastAPIUsers instance + reusable auth dependencies."""

from __future__ import annotations

import uuid

from fastapi_users import FastAPIUsers

from airalo.api.auth.backend import bearer_backend, cookie_backend
from airalo.api.auth.manager import get_user_manager
from airalo.api.auth.models import User

fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [cookie_backend, bearer_backend],
)

# Use these as ``Depends(current_active_user)`` etc. on protected routes.
current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(active=True, optional=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
