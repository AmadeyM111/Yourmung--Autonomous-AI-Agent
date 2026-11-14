# Отчёт по чистке мёртвого кода (ЧАСТИЧНО)

База: origin/main e9d4b09. Метод: `git ls-files` + подсчёт `\n` (скрипт /root/work/measure.py); достижимость: AST-граф импортов + строковые ссылки (/root/work/reach.py). vulture не запускался.

## 1. База до чистки: 5241 файл, 1 909 221 строк
tests 3082/1 051 217; ouroboros 853/416 144; web 634/213 364; devtools 197/66 655; supervisor 83/51 527; docs 117/31 535; skills 63/22 795; assets 16/14 729; scripts 51/14 480; корень 30/10 900; android 46/6 040; .github 18/5 068; site 21/3 330; packaging 18/760; deploy 8/369; prompts 4/308.
По языкам: python 4107/1 572 462; web 607/206 094; прочее 363/96 862; docs 152/31 647; android 12/2 156.

## 2. Мёртвое и ненужное (измерено)
| Класс | Что | Файлы | Строки | % базы | Уверенность |
|---|---|---|---|---|---|
| A | ouroboros-модули, недостижимые от точек входа (16 шт.: launcher_*, packaged_cli*, desktop_notifications, runtime_venv, safe_test_supervisor, size_ratchet_manifest, event_token_totals) | 16 | 4 801 | 0.25% | средняя: часть нужна тестам/devtools |
| B | отключённое в проде: делегирование/субагенты (по именам файлов) | 59 | 33 475 | 1.75% | оценка по именам, не по графу |
| B | эволюция / consciousness / image+VLM | 8+6+6 | 3 752+2 119+1 605 | 0.4% | оценка по именам |
| B | скиллы unix/windows_computer_use, ui_design, templates, device_voice и др. | 42 | 12 415 | 0.65% | оценка |
| C | android, site, packaging (кроме docker, systemd), Ouroboros.spec, build*, plist, 9 скриптов, тесты упаковки | ~115 | ~21 300 | 1.1% | высокая (удалено) |
| C | devtools/benchmarks | 181 | 62 561 | 3.3% | спорно: tests/conftest.py и ~100 тестов используют server_runner |
| C | .github (CI upstream) | 18 | 5 068 | 0.27% | не удалял |
| C | launcher.py + ouroboros/launcher_* | 12 | 5 727 | 0.3% | спорно: conftest и ~25 тестов импортируют |
| D | тесты делегирования/субагентов/эволюции/cybergym/benchmark/cowork/launcher/osworld (по именам) | 227 | 96 725 | 5.1% | оценка |
| G | llm_gigachat.py (348 строк; упоминается в 10 модулях роутинга) | 1 | 348 | 0.02% | не удалял |
Классы E (зависимости) и F (настройки/маршруты/промпты) НЕ анализировались.

## 3. Удалено в ветке cleanup/dead-code
113 файлов, 21 275 строк: 1 909 221 → 1 887 946 (−1.1%), файлов 5241 → 5128.
Состав: android/, site/, packaging (кроме docker и systemd), Ouroboros.spec, build.sh/build_linux.sh/build_windows.ps1, entitlements.plist, ouroboros/packaged_cli*.py, 9 скриптов упаковки/релиза, 15 тестов этих частей.

## 4. Проверки (одноразовые контейнеры, прод не тронут)
- pytest (ту же команду, без integration/browser/…): ДО: 53 801 passed, 244 failed, 171 errors, 297 skipped. ПОСЛЕ коммита 1: 53 349 passed, 285 failed, 183 errors, 260 skipped. Новых падений относительно базы: 67; 23 из них относились к двум тестам удалённого Linux-десктопа (удалены вторым коммитом, повторного полного прогона после этого НЕ было). Остаются ~44 новых падения: мета-тесты, которые сверяют состав репозитория (test_domain_manifest, test_architecture_facts, test_provider_lane_selection ×20, test_settings_read_seam, test_runtime_mode_elevation и др.) и ссылаются на удалённые файлы. Нужно обновить их манифесты/закрепления.
- Дымовой запуск на очищенном дереве (порт 18765, пустой /tmp/data, без токенов): /api/health = 200.
- compileall и полный список импортов отдельно не запускались (collect-only показал 16 ошибок импорта, исправлены).

## 5. Спорно (решает пользователь)
devtools/benchmarks (62.5k строк) и launcher*; тесты и код делегирования/эволюции (~130k строк по именам); .github; GigaChat; manifest-мета-тесты.

## 6. Риски и откат
Ветка не в main/deploy, прод не затронут. Откат: не мёржить / `git revert`. Ветка падает в 44 мета-тестах: PR черновой.
