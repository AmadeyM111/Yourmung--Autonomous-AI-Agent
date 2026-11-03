# Журнал выкаток

Новые записи добавляются сверху. Одна запись — одна выкатка в прод (контейнер `yourmung-agent`).

## 2026-11-03 — ядро Ouroboros 7.8.0 → 7.9.0

- **Коммит / тег:** `30d5d284d`, `yourmung-core-7.9.0` (ветка `upstream-7.9` влита в `main` fast-forward).
- **Образ:** `yourmung-ouroboros:7.9` (сборка с `OUROBOROS_INSTALL_TRACING=1`). Предыдущий: `yourmung-ouroboros:7.8`.
- **Сборка и запуск:** из чистого клона репозитория, а не из рабочей папки `~/devwork/ai-agents/yourmung`
  (там 26 незакоммиченных правок на старой ветке `ouroboros`, они не тронуты).
  Использованы локальные `.env` и `docker-compose.prod.override.yml` (в репозиторий не входят):
  данные `~/devwork/ai-agents/yourmung/data` монтируются в `/data`.

```bash
OUROBOROS_INSTALL_TRACING=1 docker compose -f docker-compose.yml -f docker-compose.prod.override.yml up -d --build
```

### Что нового в ядре 7.9.0

Несколько API-ключей на провайдера, контекстное окно маршрута по отказам, диагностика тишины вместо
убийства задачи, отчёты плановых запусков под именем расписания, приватные сообщения владельцу из «мест»,
читалки Git/CI, MCP-схемы по требованию. Подробно: release notes v7.9.0 у upstream.

### Что сделано при слиянии

- Провайдеры переведены на подключения 7.9 (`OUROBOROS_CONNECTIONS`).
- Сохранены: транскрипция (local/WhisperX/Gemini/Deepgram, pyannote), Telegram-патч аудио,
  `read_spreadsheet`, фолбэк-модель проверки безопасности.
- Модельные ключи OpenRouter (Laguna, Gemma, Nemotron) перенесены на `llm_routing.resolve_target`.
- `colab_bootstrap.py` остаётся удалённым, его тесты убраны. `EXPECTED_SCAN_PATHS = 438`.
- `docs/DOMAIN_MAP.md` и `ouroboros/domains.toml` перегенерированы (`scripts/check_domains.py --write`).

### Проверка

- Целевые прогоны проходят: smoke, safety, persistence, sentinel, defaults, domain manifest.
- Затронутые области: 3718 passed, 4 failed, ~58 не дошли (прогон завис на последнем тесте).
  Полный набор (2913 тестов) не прогонялся.
- `test_bundled_node_child_reads_projected_task_env` падает и на чистом v7.9.0 (таймаут `node` через shim, окружение).
- `test_owner_stop_provider_terminal::test_accepted_provider_wait_control_survives_storage_and_both_presenters`
  зависает; на чистом v7.9.0 за 400 с тоже не завершился.
- После запуска в логе: Supervisor ready, Dialogue ready, Telegram poller started. Ответ бота в Telegram
  и утренний/вечерний брифинг вручную не проверялись.

### Известные проблемы

- **Phoenix-трейсинг не работает:** `AttributeError: 'HTTPSpanExporter' object has no attribute '_headers'`.
  `arize-phoenix-otel 0.16.1` читает `_headers`, а `opentelemetry-exporter-otlp-proto-http` 1.45+ его убрал.
  На агента не влияет. В 7.8 пакета Phoenix в образе не было, регрессии нет.
  Исправление: constraints `opentelemetry-*<1.45` при установке tracing-зависимостей (проверено в контейнере, в код не внесено).
- Предупреждение review Telegram-расширения: нет `plugin_api: "2.0"`; уже проверенная версия продолжает грузиться.
- Путь данных в контейнере теперь `/data` вместо `/ouroboros/data` (на хосте та же папка).
- Первый запуск Claudexor 4.6.2 → 4.8.1 мигрирует хранилище движка (схема 2 → 5) без автокопии.

### Бэкап и откат

- Бэкап данных до выкатки: `~/devwork/ai-agents/yourmung-data-backup-7.8-20261103-1600.tar.gz` (2,4 ГБ).
- Старый контейнер сохранён как `yourmung-agent-7.8-old` (остановлен).

```bash
docker stop yourmung-agent
docker rename yourmung-agent-7.8-old yourmung-agent
docker start yourmung-agent
```

Хранилище движка уже могло мигрировать: для чистого отката распакуйте бэкап поверх `data` (контейнер остановлен).
`yourmung-agent-7.8-old` и бэкап удалять после нескольких дней стабильной работы.
