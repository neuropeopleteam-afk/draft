"""devops.k8s.target_port_bug — find_bug: targetPort Service не ведёт на порт приложения.

Подтип один: endpoints есть, но targetPort указывает не на слушаемый порт (номер порта Service вместо порта
контейнера или неверное имя порта) — connection refused. Генератор общий с devops.k8s.service_selector_bug.
"""
from __future__ import annotations

from ._k8s_service import generate_variant

FAMILY_ID = "devops.k8s.target_port_bug"


def generate(seed: int):
    return generate_variant(FAMILY_ID, seed, "target_port")
