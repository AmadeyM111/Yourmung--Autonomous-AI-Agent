# exec_assistant

Навык-ассистент руководителя: читает Google Calendar и Gmail, готовит черновики, ведёт реестр обязательств, собирает утреннюю и вечернюю сводки.

## Модель безопасности

- Только чтение и черновики. Навык НИКОГДА не отправляет письма и НЕ создаёт/меняет события календаря (в коде нет ни одного вызова отправки или записи в календарь).
- Права OAuth: `calendar.readonly`, `gmail.readonly`, `gmail.compose` (нужен только для создания черновиков).
- Тексты писем и календаря — недоверенные данные третьих лиц; инструкции из них не выполняются.
- Секреты читаются только из настроек, выданных навыку (grant); `exec_status` показывает лишь имена отсутствующих ключей.
- Любое исходящее действие — только после подтверждения владельца.

## Настройка

1. Создайте проект в Google Cloud Console.
2. Включите Gmail API и Google Calendar API.
3. Создайте OAuth client типа Desktop app.
4. Запустите `scripts/get_google_refresh_token.py` и пройдите авторизацию.
5. В Settings → Secrets сохраните `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`.
6. Выдайте навыку эти три ключа (grant) и включите его.
7. Примите два расписания: `morning_brief` (пн-пт 08:30 МСК) и `evening_wrap` (пн-пт 18:00).
8. Проверьте: `exec_status`.

## Инструменты

exec_status, exec_agenda, exec_conflicts, exec_free_slots, exec_event, exec_mail_triage, exec_mail_thread, exec_mail_awaiting, exec_mail_draft_reply, exec_commitment_add, exec_commitment_add_many, exec_commitment_list, exec_commitment_update, exec_commitment_done, exec_brief_morning, exec_brief_evening.

Маршрут: `GET status`. Обязательства хранятся в `commitments.json` в каталоге состояния навыка. Отдельный навык `meeting_minutes` превращает запись встречи в протокол и сохраняет задачи.
