# Чистка мёртвого кода Yourmung (форк Ouroboros 7.9): итоги этапов 1 и 2

Дата: 15 ноября 2026. Ветка `cleanup/dead-code`, draft PR #3. База сравнения: `e9d4b09f4` (ветка `deploy`/`main` на момент запуска).

## Вердикт: ЧАСТИЧНО
Классы (a), (b), (c) выполнены, валидация ветки зелёная. Класс (d) (делегирование/субагенты/эволюция) **не удалён**: граф достижимости показал, что его нельзя вырезать, не переписав прод-путь и запретные файлы (см. «Спорно»). Класс (e) (неиспользуемые зависимости) сделан только для `gigachat`.
Новые падения pytest: 0 после проверки (в сыром сравнении по именам 35 «новых», все 35 повторно прогнаны отдельно и совпали с базой, это шум от параллельной нагрузки, см. ниже).
Автодеплой не затронут: в `main` и `deploy` ничего не пушилось, PR не смёржен.

## 1. Размер до и после (метод: `git ls-files`, подсчёт `\n`)
| | файлов | строк |
|---|---|---|
| База (e9d4b09f4) | 5241 | 1 909 221 |
| После | 4846 | 1 768 295 |
| Удалено | 395 | 140 926 (7,4%) |

`git diff --shortstat e9d4b09f4 HEAD`: 516 файлов изменено, 163 добавлено, 140 279 удалено (чистая разница).
По каталогам (удалённые строки): devtools 58 917, tests 57 308, android 6 040, .github 5 068, ouroboros 4 082, site 3 330, scripts 2 282, launcher.py 1 600, packaging 499.

## 2. Что удалено по классам
- **Этап 1 (C): упаковка/сайт/релизные скрипты**: android, site, packaging (кроме docker и systemd), Ouroboros.spec, build*, packaged_cli*, 9 скриптов, их тесты. −20 909 и −366 строк.
- **(a) launcher и бенчмарки**: `launcher.py`, `ouroboros/launcher_*` (кроме двух модулей, см. «Оставлено»), `devtools/benchmarks/*` (кроме `common/`), тесты `test_launcher_*`, `test_cowork_*`, `test_cybergym_*`, `test_osworld_*`, `test_swe_*` и др., стадия `managed` в Dockerfile. −107 588 строк.
- **(b) GigaChat**: `ouroboros/llm_gigachat.py`, ветки в `llm.py`, `llm_routing.py`, `llm_probe.py`, `gateway/models.py`, `provider_models.py`, `pricing.py`, `vision_routing.py`, `settings_defaults.py`, карточка в веб-настройках и JS-тесты, зависимость `gigachat` в `pyproject.toml`, `uv.lock`, `requirements-runtime.lock`, golden-фикстуры, тесты. −4 278 строк.
- **(c) `.github`** целиком (18 файлов) и 11 тестовых файлов про CI: −9 242 строки.
- **Тесты**: удалено примерно 3 100 тестов (pytest passed 53 878 → 50 778), все привязаны к удалённому коду. Перечень: `/root/work/removed_tests_log.txt`.
- **Пины**: перегенерированы `domains.toml`, `DOMAIN_MAP.md`, `docs/inventories/*`; поправлены `PERSISTENCE.md`, `FLOOR_TESTS` в `ouroboros/test_selection.py`, число путей в `test_persistence_inventory`, хеш в `test_llm_extraction`.

## 3. Валидация (ДО = база e9d4b09f4, ПОСЛЕ = ветка 4fb7e8184)
| Проверка | ДО | ПОСЛЕ |
|---|---|---|
| compileall | — | OK (код 0) |
| Импорт модулей `ouroboros.*`, `supervisor.*`, `server` | 933 модуля, 0 не импортируются | 920 модулей, 0 не импортируются |
| pytest (фильтр как в базе, без integration/browser) | 53 878 passed, 210 failed, 132 errors | 50 778 passed, 189 failed, 166 errors |
| Новые падения по именам | — | 35 сырых, 0 после перепроверки |
| Смоук (порт 18765, пустые данные, без токенов) | — | `/api/health` 200, `/api/mcp/status` 200 |
| `patch_tools.py` на файле ветки | applied | applied (`registry_guards.py` байт-в-байт как в базе) |
| `patch_voice.py` | — | импорты `skill_install_record`/`skill_loader` резолвятся; сам патч правит файл плагина в `data/`, не в ветке, поэтому на дереве ветки целиком не воспроизводился |
| Сборка образа `docker build` (временный тег) | — | OK, 55 с, тег удалён |

**О 35 «новых» падениях.** Это 33 в `test_cost_contract.py` (ошибки фикстуры при нагрузке), 1 в `test_server_capture_exit.py`, 1 в `test_terminal_maintenance_independence.py`. Отдельный прогон при малой нагрузке: `test_cost_contract` 192 passed и на базе, и на ветке; `test_server_capture_exit` проходит; `test_terminal_maintenance_independence` на базе и на ветке даёт одинаково 8 passed, 4 errors. Базовые 342 падения (210+132) существовали до чистки (часть зависит от окружения).

## 4. Оставлено и почему («спорно»)
- **(d) Делегирование/субагенты/эволюция/consciousness**: 61 модуль, 29 692 строки в `ouroboros/`. Их импортируют 190 других модулей, из них 42 в запретных зонах (`safety.py`, `runtime_mode_policy.py`, `tools/registry_core.py`, `registry_guards.py`, `tool_resolution.py`, `supervisor/*`). Удаление потребует переписать эти файлы и прод-путь. Карта: `/root/work/reach_stage2.txt`, `/root/work/grp_out.txt`. Реальный объём кода ниже оценки «130 тыс.» (оценка включала тесты).
- `ouroboros/launcher_bootstrap.py`: импортируется `server.py`, `agent`, `loop`, `context`.
- `ouroboros/launcher_server_reaper.py`: используется стартовой проверкой лишних серверных процессов (`agent_startup_checks`).
- `devtools/benchmarks/common/` и `tests/system_e2e/`: тестовый харнесс, на нём держатся тесты прод-логики.
- Упоминания GigaChat в `secret_masking.py`, `observability.py` (маскирование секретов), `contracts/plugin_api.py` (замороженный контракт), `server_runtime.py` (список старых моделей), `net_transport.py` (комментарии): безвредны, маскирование полезно для старых значений в `settings.json`.
- Тесты сервисного слоя host-service и презенса возвращены; для них добавлен `tests/_native_guard.py` вместо фикстуры из удалённых тестов launcher.
- Класс (e): неиспользуемые зависимости не разбирались (кроме `gigachat`); `pydantic-settings` в `uv.lock` мог остаться без потребителя.
- 4 вида тестов удалены целиком вместе с кодом: потеряно покрытие desktop-хоста, CI, бенчмарков; покрытие прод-логики через `system_e2e` и host-service сохранено.

## 5. Ссылки
Ветка: https://github.com/AmadeyM111/Yourmung--Autonomous-AI-Agent/tree/cleanup/dead-code  PR: https://github.com/AmadeyM111/Yourmung--Autonomous-AI-Agent/pull/3

## 6. Риски и откат
- Риск: в веб-UI удалена карточка GigaChat; в `settings.json` могут оставаться ключи `GIGACHAT_*` (игнорируются, маскируются).
- Риск: `Dockerfile` больше не имеет стадии `managed`; боевой стейдж `runtime` и compose не менялись.
- Откат: не мёржить PR; уже в `main` ничего нет. После мёржа: `git revert -m 1 <merge>` или вернуть `deploy` на `e9d4b09f4`.
- Прод не трогался: контейнеры, `data/`, `.env`, туннель, автодеплой.
