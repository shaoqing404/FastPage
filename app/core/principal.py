from dataclasses import dataclass

from app.models import ApiKey, User


@dataclass
class Principal:
    kind: str
    tenant_id: str
    user: User
    api_key: ApiKey | None = None

    @property
    def user_id(self) -> str:
        return self.user.id
