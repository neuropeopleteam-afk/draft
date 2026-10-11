"""devops.k8s.service_selector_bug — find_bug: селектор Service не совпадает с метками подов.

Подтип один: Service не выбирает ни одного пода (значение метки, лишняя пара version, другой ключ метки) —
endpoints пусты. Генератор общий с devops.k8s.target_port_bug (_k8s_service.py).
"""
from __future__ import annotations

from ._k8s_service import generate_variant

FAMILY_ID = "devops.k8s.service_selector_bug"


def generate(seed: int):
    return generate_variant(FAMILY_ID, seed, "selector")
