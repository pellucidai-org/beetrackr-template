"""SQLAlchemy User model.

Uses :class:`fastapi_users.db.SQLAlchemyBaseUserTableUUID` which provides::

    id (UUID, PK)
    email (str, unique, indexed)
    hashed_password (str)
    is_active (bool, default True)
    is_superuser (bool, default False)
    is_verified (bool, default False)

The class is attached to the project-wide :class:`Base` declared in
:mod:`airalo.storage.models` so it shares the same metadata as
``scraped_items`` and ``page_artifacts``. A single ``create_all`` builds
every table the project owns.
"""

from __future__ import annotations

from fastapi_users.db import SQLAlchemyBaseUserTableUUID

from beets.storage.models import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """API user. PK is UUID, email is the login identifier."""

    __tablename__ = "users"
