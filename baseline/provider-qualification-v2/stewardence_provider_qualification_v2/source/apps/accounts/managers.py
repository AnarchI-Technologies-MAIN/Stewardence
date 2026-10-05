from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    @staticmethod
    def normalize_identity(email: str) -> str:
        if not email:
            raise ValueError("An email address is required")
        return BaseUserManager.normalize_email(email).strip().lower()

    def get_by_natural_key(self, username: str):
        return self.get(email__iexact=self.normalize_identity(username))

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ):
        email = self.normalize_identity(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True")
        return self.create_user(email, password, **extra_fields)
