# Направление devops — DevOps / SRE

Семейства направления «DevOps / SRE»: bash и Linux, Docker, CI, манифесты Kubernetes, мониторинг
(Prometheus), SLO и бюджет ошибок, сети (iptables, nginx), ведение инцидентов.

Семейств уровней Стажёр–Senior: **21**. Покрытие уровней (семейство может целиться в два соседних): Стажёр — 3, Junior — 14, Middle — 16, Senior — 7.
Семейства уровней Lead/Principal (файлы с префиксами `lead_`/`principal_`, 3 шт.) — отдельный набор,
проверяется `tests/test_lead_principal_a.py`.

## Как устроены семейства
- Каждое семейство — параметрический генератор: контекст, данные, имена и числа меняются от seed; не меньше 20
  различимых вариантов (`tools/check_family_variants.py`, расстояние Жаккара по словам видимого текста ≥ 0,05).
- Ключ закрытых форматов проверяется исполнением в песочнице; у open_book_3step шаги 1–2 исполняются, шаг 3 и
  open_answer оцениваются по рубрике из трёх критериев с весами и эталонами «сильный/средний/слабый».
- Конфигурации, которые в песочнице не исполнить (манифесты Kubernetes, Dockerfile, правила iptables, nginx,
  конфигурация CI, правила алертов), проверяются моделью на Python: программа проверки содержит показанный текст
  дословно (r-строка), разбирает его и применяет правила из документации (выбор Service по селектору, targetPort,
  класс QoS, maxSurge/maxUnavailable, ENTRYPOINT/CMD, первое совпавшее правило iptables, выбор location в nginx,
  for в правилах алертов, histogram_quantile, needs в CI). bash-семейства исполняются настоящим bash.
- Дистракторы — фиксированный состав типовых ошибок (одна главная ловушка на семейство), чтобы задание различало
  соседние уровни, а не случайно усложнялось.
- `prior_difficulty` — априорная трудность (не по людям) с обоснованием `basis`; калибровка — общим прогоном панели.
- Навыки (`skills`) — из словаря каталога направлений (снимок в `tests/test_devops_de.py`).

## Семейства

| семейство | формат | уровни | b | что проверяет | ключ |
|---|---|---|---|---|---|
| `devops.bash.exit_status_output` | predict_output | Стажёр, Junior | -1.2 | bash — коды возврата в списках && / \|\| и $? | исполнение: bash |
| `devops.bash.param_expansion_canary` | predict_output | Junior | -1.0 | bash — раскрытие параметров (канарейка) | исполнение: bash |
| `devops.bash.pipefail_fix` | choose_fix | Junior, Middle | +0.0 | bash — set -e не ловит падение в конвейере с tee (pipefail) | исполнение: bash |
| `devops.bash.quoting_bug` | find_bug | Junior, Middle | -0.5 | bash — переменная с путём без кавычек (разбиение на слова) | исполнение: bash |
| `devops.bash.redirect_order_output` | predict_output | Стажёр, Junior | -1.1 | Bash — порядок перенаправлений stdout и stderr | исполнение: bash |
| `devops.bash.retry_ob3` | open_book_3step | Middle, Senior | +0.7 | bash — retry возвращает 0 после исчерпания попыток (открытая книга) | шаги 1–2 — исполнение (bash), шаг 3 — рубрика |
| `devops.ci.job_needs_output` | predict_output | Junior, Middle | +0.1 | CI (GitHub Actions) — статусы job после падения одной (needs, always, failure) | исполнение: python |
| `devops.docker.entrypoint_cmd_mcq` | mcq_concept | Junior, Middle | -0.4 | Docker — какой процесс запустит docker run при ENTRYPOINT и CMD | исполнение: python |
| `devops.inc.incident_open` | open_answer | Senior | +1.3 | Ведение инцидента в продакшене — стабилизация, причина, действия после | рубрика |
| `devops.k8s.hpa_replicas_ob3` | open_book_3step | Middle, Senior | +0.9 | Kubernetes — расчёт реплик как в HPA, округление вниз (открытая книга) | шаги 1–2 — исполнение (python), шаг 3 — рубрика |
| `devops.k8s.qos_class_mcq` | mcq_concept | Junior, Middle | -0.2 | Kubernetes — класс QoS пода по requests и limits | исполнение: python |
| `devops.k8s.rolling_update_mcq` | mcq_concept | Junior, Middle | +0.1 | Kubernetes — границы RollingUpdate по maxSurge и maxUnavailable | исполнение: python |
| `devops.k8s.service_selector_bug` | find_bug | Junior, Middle | -0.4 | Kubernetes — селектор Service не совпадает с метками подов | исполнение: python |
| `devops.k8s.target_port_bug` | find_bug | Junior, Middle | -0.1 | Kubernetes — targetPort Service не ведёт на порт приложения | исполнение: python |
| `devops.linux.permissions_output` | predict_output | Стажёр, Junior | -1.2 | Linux — права доступа к файлу (владелец, группа, остальные) | исполнение: python |
| `devops.mon.alert_for_mcq` | mcq_concept | Middle, Senior | +0.6 | Мониторинг — когда алерт Prometheus с for перейдёт в firing | исполнение: python |
| `devops.mon.histogram_quantile_mcq` | mcq_concept | Middle, Senior | +0.8 | Мониторинг — что вернёт histogram_quantile по корзинам гистограммы | исполнение: python |
| `devops.net.iptables_order_output` | predict_output | Junior, Middle | -0.2 | Сети — цепочка INPUT iptables, порядок правил и вставка -I | исполнение: python |
| `devops.net.nginx_location_mcq` | mcq_concept | Middle, Senior | +0.5 | Сети — какой location nginx обработает запрос | исполнение: python |
| `devops.sre.burn_rate_mcq` | mcq_concept | Middle, Senior | +1.0 | SRE — многооконные алерты по скорости расхода бюджета ошибок | исполнение: python |
| `devops.sre.error_budget_mcq` | mcq_concept | Junior, Middle | -0.3 | SRE — остаток бюджета ошибок после полного, частичного отказа и замедления | исполнение: python |

## Проверки
```bash
make test-fast                                              # быстрые тесты, включая tests/test_devops_de.py
python tools/dev_family.py <family_id> 200 --show 1         # одно семейство: 200 seed, пример варианта
python tools/check_family_variants.py --direction devops   # ≥ 20 различимых вариантов
python -m assessment_bank validate --seeds 200 --out reports
```
