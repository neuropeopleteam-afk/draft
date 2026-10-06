"""Общий интерфейс ATS-провайдера: проверка подключения, вакансии и этапы для выбора, передача кандидата.

Каждый провайдер (Хантфлоу, Talantix, «Поток») реализует четыре метода. Идемпотентность — общая: перед передачей
сервис берёт ``LinkState`` (кандидат платформы → id кандидата в ATS и вакансии, на которые он уже добавлен);
провайдер не создаёт кандидата заново, если id уже известен, и сохраняет id сразу после создания
(``LinkState.save``) — даже если следующий шаг упадёт, повтор продолжит с того же места.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.integrations.ats.clients import AtsError  # noqa: F401 — реэкспорт для провайдеров


@dataclass
class Target:
    """Куда передать: вакансия и этап в ATS (None — только в базу кандидатов)."""

    vacancy_id: int | None = None
    vacancy_title: str | None = None
    stage_id: int | None = None
    stage_title: str | None = None


@dataclass
class LinkState:
    external_id: str | None = None
    vacancies: list[dict] = field(default_factory=list)
    saver: Callable[["LinkState"], None] | None = None

    def on_vacancy(self, vacancy_id: int | None) -> dict | None:
        return next((v for v in self.vacancies if vacancy_id and v.get("id") == vacancy_id), None)

    def save(self, *, external_id: str | int | None = None, vacancy: dict | None = None) -> None:
        if external_id is not None:
            self.external_id = str(external_id)
        if vacancy and vacancy.get("id"):
            self.vacancies = [v for v in self.vacancies if v.get("id") != vacancy["id"]] + [vacancy]
        if self.saver:
            self.saver(self)


class Provider:
    code: str = ""
    title: str = ""

    def check(self) -> dict:  # pragma: no cover — интерфейс
        """{"ok": True, "account": "…", "details": […]} или AtsError."""
        raise NotImplementedError

    def vacancies(self) -> list[dict]:  # pragma: no cover
        """[{"id", "title", "status", "department", "url"}] — для выбора вакансии в настройках."""
        raise NotImplementedError

    def stages(self, vacancy_id: int) -> list[dict]:  # pragma: no cover
        """[{"id", "title"}] — этапы подбора вакансии (необязательный выбор)."""
        raise NotImplementedError

    def push(self, d: dict, target: Target, link: LinkState, *, force: bool = False) -> dict:  # pragma: no cover
        """Передать кандидата (d — profile.build). Возвращает результат для журнала без ПДн."""
        raise NotImplementedError


def soft(steps: list[str], title: str, fn: Callable[[], object]) -> object | None:
    """Необязательный шаг (комментарий, этап, источник): ошибка попадает в журнал, но передачу не валит."""
    try:
        return fn()
    except AtsError as e:
        steps.append(f"{title}: не удалось — {e}")
        return None
