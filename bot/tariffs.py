"""Tariff and service definitions for subscription plans.

This module centralizes configuration for all services ("тарифы") that the
bot can sell. Each service describes:

* which inbound in the XUI panel it should use,
* how to derive a unique email/identifier for a Telegram user,
* which plans (duration & price) are available,
* optional flags such as admin-only plans.

Adding a new service now only requires defining another ``TariffService`` instance
below and wiring its inbound id / suffix in the environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import os

# Optional env-driven overrides for inbound ids & suffixes. Default values keep
# backward compatibility with the single-tariff setup.
_DEFAULT_SERVER_HOST = os.getenv("SERVER_HOST", "77.110.118.156")
_DEFAULT_STANDARD_INBOUND_ID = int(os.getenv("TARIFF_STANDARD_INBOUND_ID", "1"))
_DEFAULT_OBHOD_INBOUND_ID = int(os.getenv("TARIFF_OBHOD_INBOUND_ID", "2"))
_DEFAULT_STANDARD_VM_INBOUND_ID = int(os.getenv("TARIFF_STANDARD_VM_INBOUND_ID", "6"))
_DEFAULT_STANDARD_HOST = os.getenv("TARIFF_STANDARD_SERVER_HOST", _DEFAULT_SERVER_HOST)
_DEFAULT_OBHOD_HOST = os.getenv("TARIFF_OBHOD_SERVER_HOST", _DEFAULT_SERVER_HOST)
_DEFAULT_STANDARD_VM_HOST = os.getenv("TARIFF_STANDARD_VM_SERVER_HOST", _DEFAULT_SERVER_HOST)
_DEFAULT_STANDARD_VM_SUFFIX = os.getenv("TARIFF_STANDARD_VM_EMAIL_SUFFIX", "-vmess")
_DEFAULT_OBHOD_SUFFIX = os.getenv("TARIFF_OBHOD_EMAIL_SUFFIX", "-obhod")


@dataclass(frozen=True)
class TariffPlan:
    key: str
    label: str
    days: int
    amount_minor: int  # amount in minor currency units (e.g. kopecks)
    admin_only: bool = False

    def describe(self) -> str:
        return f"{self.label} — {self.days} дн."


@dataclass(frozen=True)
class TariffService:
    key: str
    name: str
    description: str
    inbound_id: int
    email_suffix: str = ""
    server_host: Optional[str] = None
    plans: List[TariffPlan] = field(default_factory=list)
    protocol: str = "vless"
    visible: bool = True
    auto_assign_on_purchase: bool = False
    sync_priority: int = 5

    def email_for_user(self, tg_id: int) -> str:
        base = str(tg_id)
        return base if not self.email_suffix else f"{base}{self.email_suffix}"

    def plans_for_user(self, is_admin: bool) -> Iterable[TariffPlan]:
        for plan in self.plans:
            if plan.admin_only and not is_admin:
                continue
            yield plan


DEFAULT_SERVICE_KEY = "standard"


_SERVICES: Dict[str, TariffService] = {
    "standard": TariffService(
        key="standard",
        name="Стандартный",
        description=(
            "Основной тариф: дешёво, быстро, удобно. Идеальное соотношение цена-качество."
        ),
        inbound_id=_DEFAULT_STANDARD_INBOUND_ID,
        email_suffix="",
        server_host=_DEFAULT_STANDARD_HOST,
        plans=[
            TariffPlan("test", "🧪 Тест — 1₽ (1 день)", days=1, amount_minor=100, admin_only=True),
            TariffPlan("1m", "1 месяц — 149₽", days=30, amount_minor=14900),
            TariffPlan("3m", "3 месяца — 369₽", days=90, amount_minor=36900),
            TariffPlan("6m", "6 месяцев — 599₽", days=180, amount_minor=59900),
        ],
        protocol="vless",
        visible=True,
        auto_assign_on_purchase=False,
        sync_priority=0,
    ),
    "obhod": TariffService(
        key="obhod",
        name="Всегда на связи",
        description=(
            "Альтернативный канал. Позволяет ускорить мобильный интернет в таких городах, как "
            "Ижевск, Киров и среднее Поволжье. ⚠️ Мобильный интернет ускоряется не на всех операторах."
        ),
        inbound_id=_DEFAULT_OBHOD_INBOUND_ID,
        email_suffix=_DEFAULT_OBHOD_SUFFIX,
        server_host=_DEFAULT_OBHOD_HOST,
        plans=[
            TariffPlan("test", "🧪 Тест — 1₽ (1 день)", days=1, amount_minor=100, admin_only=True),
            TariffPlan("1d", "1 день — 29₽", days=1, amount_minor=2900),
            TariffPlan("1w", "1 неделя — 99₽", days=7, amount_minor=9900),
            TariffPlan("1m", "1 месяц — 179₽", days=30, amount_minor=17900),
            TariffPlan("3m", "3 месяца — 399₽", days=90, amount_minor=39900),
            TariffPlan("6m", "6 месяцев — 599₽", days=180, amount_minor=59900),
        ],
        protocol="vless",
        visible=True,
        auto_assign_on_purchase=False,
        sync_priority=1,
    ),
    "standard_vm": TariffService(
        key="standard_vm",
        name="Стандартный #2",
        description=(
            "Дополнительный VMess-доступ. Выдаётся автоматически при покупке любого тарифа."
        ),
        inbound_id=_DEFAULT_STANDARD_VM_INBOUND_ID,
        email_suffix=_DEFAULT_STANDARD_VM_SUFFIX,
        server_host=_DEFAULT_STANDARD_VM_HOST,
        plans=[],
        protocol="vmess",
        visible=False,
        auto_assign_on_purchase=True,
        sync_priority=2,
    ),
}


def all_services(include_hidden: bool = False) -> List[TariffService]:
    services = list(_SERVICES.values())
    if include_hidden:
        return services
    return [service for service in services if service.visible]


def auto_assign_services() -> List[TariffService]:
    return [service for service in _SERVICES.values() if service.auto_assign_on_purchase]


def get_service(key: str) -> Optional[TariffService]:
    return _SERVICES.get(key)


def get_plan(service_key: str, plan_key: str) -> Optional[TariffPlan]:
    service = get_service(service_key)
    if not service:
        return None
    for plan in service.plans:
        if plan.key == plan_key:
            return plan
    return None


def get_service_by_inbound_id(inbound_id: int) -> Optional[TariffService]:
    try:
        inbound_id_int = int(inbound_id)
    except (TypeError, ValueError):
        return None
    for service in _SERVICES.values():
        if int(service.inbound_id) == inbound_id_int:
            return service
    return None


__all__ = [
    "TariffPlan",
    "TariffService",
    "DEFAULT_SERVICE_KEY",
    "all_services",
    "auto_assign_services",
    "get_service",
    "get_plan",
    "get_service_by_inbound_id",
]
