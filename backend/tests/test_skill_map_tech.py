"""Сведение навыков технологических семейств банка (Go, Java, Django, Kafka, Docker) к стек-тегам справочника."""
from app.modules.assessment.skill_map import to_stack_tags
from app.modules.catalog.seed_data import STACK


def test_tech_tags_exist_in_catalog():
    for tag in ("docker", "kafka", "django", "go", "java"):
        assert tag in STACK


def test_backend_tech_families_map_to_own_tags():
    assert to_stack_tags("backend", ["go", "goroutines", "go_channels", "data_races", "sync_mutex"]) == ["go"]
    assert to_stack_tags("backend", ["java", "java_streams", "completable_future"]) == ["java"]
    assert to_stack_tags("backend", ["django", "django_orm", "n_plus_one", "python"]) == ["django", "python"]
    assert to_stack_tags("backend", ["kafka", "kafka_consumer_groups", "kafka_partitions"]) == ["kafka"]


def test_tech_skills_do_not_leak_into_other_tags():
    # гонки в Go не подтверждают asyncio, Kafka не подтверждает RabbitMQ
    assert "asyncio" not in to_stack_tags("backend", ["go", "data_races", "goroutines"])
    assert "rabbitmq" not in to_stack_tags("backend", ["kafka", "kafka_delivery", "kafka_offsets"])


def test_docker_is_common_for_every_direction():
    for d in ("backend", "frontend", "data_ml", "qa", "security"):
        assert to_stack_tags(d, ["docker", "dockerfile", "docker_build_cache"]) == ["docker"]


# ------------------------------------------------------------------ фильтр по стеку при выдаче (07.10, Р2)

def test_stack_gate_only_for_tech_tags():
    from app.modules.assessment.skill_map import STACK_GATED, allowed_for_stack, stack_gate

    assert stack_gate("backend", ["go", "goroutines"]) == {"go"}
    assert stack_gate("backend", ["django", "django_orm", "python"]) == {"django"}
    assert stack_gate("common", ["docker", "dockerfile"]) == {"docker"}
    # обычные семейства — без условия: выдаются всем
    assert stack_gate("backend", ["python", "asyncio", "fastapi"]) == frozenset()
    assert stack_gate("common", ["sql", "joins"]) == frozenset()
    assert STACK_GATED == {"go", "java", "django", "kafka", "docker"}


def test_allowed_for_stack():
    from app.modules.assessment.skill_map import allowed_for_stack

    assert allowed_for_stack("backend", ["go", "go_slices"], ["python", "go"])
    assert not allowed_for_stack("backend", ["go", "go_slices"], ["python"])
    assert not allowed_for_stack("backend", ["go", "go_slices"], None)
    assert allowed_for_stack("backend", ["python", "dict"], None)
    # семейство с двумя технологическими тегами требует оба
    assert not allowed_for_stack("backend", ["kafka", "docker"], ["kafka"])
    assert allowed_for_stack("backend", ["kafka", "docker"], ["kafka", "docker"])
