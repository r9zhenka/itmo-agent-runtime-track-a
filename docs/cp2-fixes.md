# Исправления после проверки вопросов ЧП2

Этот документ описывает изменения после опубликованного коммита `64ea82a`,
зафиксированные локально в runtime-ревизии `0366b1c` и test-only исправлении
`b37dedd` (fixture для crash acceptance), затем portability-исправлении
`b117d62` (`project-a-observation-v2`).
Исторические измерения, 117 live-попыток и их исправленные оценки не переписывались.
[Исходный отчёт](cp2-report.md), [цепочка evidence](evidence/cp2/README.md) и
[коррекции оценивания](evaluation-corrections.md) относятся к указанным в них
ревизиям. Новая функциональность прошла отдельную Ubuntu-приёмку на `b117d62`;
старый зелёный GitHub CI её не подтверждает.

[Схемы](cp2-architecture.md) показывают актуальные границы машин, контейнеров,
протоколов и доверия. [Разбор реальных трейсов](cp2-trace-walkthrough.md) объясняет
успех B1.1, отмену C3 и различия серверного/клиентского времени без выдуманных
аргументов инструментов. [Ответы на вопросы ЧП2](checkpoint-2-answers.md) связывают
реализацию с общей частью и вопросами A1–A26.

## Дефект → исправление → проверка

| Найденная проблема | Изменение и код | Регрессионная/приёмочная проверка | Оставшаяся граница |
|---|---|---|---|
| SSE-клиент мог переслать Authorization при HTTP redirect | [client/api.py](../client/api.py): запрет перенаправлений для клиентских запросов, включая события | [test_cp2_lifecycle.py](../tests/test_cp2_lifecycle.py): `test_event_redirect_does_not_forward_authorization`; аналогичная проверка provider в [test_provider_network.py](../tests/test_provider_network.py) | Клиент по-прежнему должен доверять первоначально выбранному серверу и проверять SSH fingerprint |
| Владение сессией фактически сводилось к общему токену | [gateway.py](../runtime/gateway.py), [common.py](../runtime/common.py): `CLIENT_IDENTITIES_JSON`, principal-владелец, проверки чтения/изменения, namespace create request ID | `test_identity_cannot_read_or_mutate_another_session` в [test_cp2_lifecycle.py](../tests/test_cp2_lifecycle.py) | Это разделение HTTP-сессий; общий SSH-аккаунт, Docker-хост и доступные ему каталоги не превращаются в изолированные ОС-тенанты |
| Освобождённые сессии навсегда занимали лимит активных | [harness.py](../runtime/harness.py), [sandbox_manager.py](../runtime/sandbox_manager.py): отдельные active и closed; active 128/512, целевой closed retention 128 | `test_released_sessions_do_not_exhaust_active_capacity`, `test_many_released_sessions_do_not_exhaust_manager_capacity` в [lifecycle](../tests/test_cp2_lifecycle.py) и [sandbox events](../tests/test_sandbox_events.py) | Очистка closed происходит при новом create/provision; между ними количество может временно превышать 128. После eviction теряются cursor/idempotency; состояния после restart нет |
| Отмена между шагами могла опубликовать успех cleanup до его окончания | [harness.py](../runtime/harness.py): терминальную отмену публикует cancel-владелец после подтверждения остановки; failure остаётся error | `test_cancel_between_steps_waits_for_cleanup_and_reports_failure`; `test_cancelled_operation_stream_has_one_terminal_after_cleanup` | Недоступность Docker/control plane может задержать фактическое удаление; это не превращается в ложное подтверждение отмены |
| Блокирующий sandbox RPC не давал наблюдать ход операции | [sandbox_manager.py](../runtime/sandbox_manager.py): `start` + `events`; [common.py](../runtime/common.py): `Remote.execute`; [harness.py](../runtime/harness.py): `tool_progress` | [test_sandbox_events.py](../tests/test_sandbox_events.py): running до завершения, повтор запроса без повторного действия, один terminal | Передаются статусы started/running/result, не поток stdout по байтам и не токены модели. Legacy `exec` сохранён |
| Обрыв HTTP событий мог терять частично полученный ответ или повторять события | [client/api.py](../client/api.py): возобновление с последнего подтверждённого seq, дедупликация | `test_real_interrupted_event_response_resumes_and_deduplicates` в [test_cp2_lifecycle.py](../tests/test_cp2_lifecycle.py) использует настоящий loopback HTTP disconnect | Возобновляется чтение событий, не исполнение операции; после рестарта/eviction старые события недоступны |
| Сбой записи trace или запуска worker мог оставить run зависшим | [harness.py](../runtime/harness.py), [sandbox_manager.py](../runtime/sandbox_manager.py): управляемый терминальный исход и освобождаемое состояние | [test_cp2_lifecycle.py](../tests/test_cp2_lifecycle.py), [test_review_regressions.py](../tests/test_review_regressions.py): disk failure, thread launch failure, повтор request ID | Trace storage не стал транзакционным журналом для восстановления сессий |
| Долгий create удерживал общую блокировку авторизации gateway | [gateway.py](../runtime/gateway.py): медленный upstream вне общей критической секции | `test_slow_create_does_not_hold_gateway_authorization_lock` в [test_review_regressions.py](../tests/test_review_regressions.py) | Один workspace всё равно не допускает конфликтующие активные сессии |
| SIGKILL SSH-helper оставлял rclone/FUSE без владельца cleanup | [mount_guard.py](../runtime/mount_guard.py), [remote_mount.py](../runtime/remote_mount.py): отдельный процесс владеет FUSE/lease, EOF control pipe запускает отзыв и unmount | [test_workspace_conflicts.py](../tests/test_workspace_conflicts.py), реальный [check_mount_crash.py](../scripts/check_mount_crash.py) | SIGKILL самого guard, отказ хоста или unmount могут требовать ручного восстановления; lease/deadline ограничивает команды, но не гарантирует доступность Docker |
| Parent/child экспорты обходили блокировку одного каталога | [workspace_server.py](../client/workspace_server.py): межпроцессные shared-locks предков и exclusive-lock целевого inode в registry текущего UID | `test_parent_child_conflicts_in_both_directions_but_siblings_work`, `test_cross_process_overlap_rejected_and_sigkill_releases_registry_locks` | Registry не является глобальной блокировкой других ОС-пользователей/машин и не контролирует действия локального редактора |
| PUT/MOVE/DELETE могли не замечать устаревшее содержимое перед изменением | [workspace_server.py](../client/workspace_server.py): ETag preconditions, повторная проверка source/destination версии после подготовительных операций | [test_workspace_conflicts.py](../tests/test_workspace_conflicts.py): stale/current ETag, изменение во время quota scan, source/destination changes | Между последней проверкой и системным вызовом остаётся окно гонки с внешним редактором. Полной POSIX/распределённой транзакции нет |
| Provider error скрывал тип сбоя и известный usage | [provider_transport.py](../runtime/provider_transport.py), [llm_proxy.py](../runtime/llm_proxy.py), [harness.py](../runtime/harness.py): безопасная категория, HTTP status/finish_reason и известные токены | [test_provider_network.py](../tests/test_provider_network.py), `test_provider_failure_preserves_safe_details_and_known_usage` | При отсутствии usage провайдером расход остаётся неизвестным; response body, ключи и секретные URL не попадают в публичную ошибку |
| Старые crash probes вызывали watchdog из тестового процесса | [check_watchdog_crash.py](../scripts/check_watchdog_crash.py): SIGKILL реальных контейнеров disposable Compose; manager-case требует собственного лога surviving watchdog с точным container ID | [test_watchdog_acceptance.py](../tests/test_watchdog_acceptance.py) проверяет предохранители; новая реальная приёмка запускается через [check_all.py](../scripts/check_all.py) | Unit-тесты не доказывают deployed cleanup. Старые 10 hardening checks сохранены как исторические; текущие восемь resource checks и два controller-crash сценария разделены |
| Синтетический replay не был записью настоящего модельного ответа | [model_recording.py](../runtime/model_recording.py), [record_smoke.py](../scripts/record_smoke.py), [check_recordings.py](../scripts/check_recordings.py): явные fixture-only capture/playback режимы | [test_model_recording.py](../tests/test_model_recording.py); аудит девяти записей и real-runtime recorded smoke в `check_all` | Запись проверяет воспроизводимость конкретных fixtures; это не новая оценка качества, не общая запись произвольного разговора |

Изменения протокола отражены в [JSON schemas](../contracts/),
[protocols.md](protocols.md), [harness.md](harness.md) и ADR
[0005](adr/0005-mounting.md)/[0006](adr/0006-sessions.md).

## Recorded smoke

`LLM_MODE=live-record` обращается к реальному провайдеру и сохраняет его ответы
только для девяти точных свежих smoke-prompts B1.1–B9.1. Файл содержит provider
response, идентификатор модели, hash fixture и hash контекста каждого шага.
Завершённую запись нельзя незаметно перезаписать. Обычный `live` этот механизм
не включает, а исторические 117 попыток не получают задним числом отсутствовавшие
полные ответы модели.

`LLM_MODE=recorded` использует сохранённые ответы, проверяет историю assistant,
fixtures, tools и содержимое наблюдений. Базовая нормализация убирает непрозрачные runtime IDs, длительность операции
и elapsed-время unittest в выводе команд. Для переноса FUSE → обычный bind добавлен
версионированный normalizer `project-a-observation-v2` в
[recorded_context.py](../runtime/recorded_context.py). Он применяется только к
начальному long-listing фактической команды `ls -la /work[/path]` или `ls -al` и
игнорирует block count, права, UID/GID, число ссылок, timestamps и размеры
директорий. Имена, типы записей, размеры обычных файлов и порядок самого ls остаются
значимыми. Версия v2 дополнительно устраняет две доказанные разницы порядка
обхода файловой системы: только при точном task prompt и точной записанной
команде B2.1 сортируются три валидные записи `path:line:content` между двумя
точными разделителями `---`; только для точной команды B9.1 сортируется полный
двухстрочный find-блок `facts.json`/`style.md` (он меньше ограничения head=50).
Другие команды grep/find, секции и порядок не нормализуются. Содержимое записей,
имена, число элементов, кратность повторов, последующий вывод, stderr и
exit/error/status сохраняют значение. Ошибки и содержимое ReadFile не
нормализуются. Изменение существенного наблюдения прерывает playback. Это особенно полезно для обнаружения несовместимого изменения
контрактов, но не обещает воспроизводить изменённую среду или произвольный shell
output.

Девять исходных JSON-записей в [baf/recordings](../baf/recordings/) сохранены
без изменения байтов. Отдельные девять `*.context.json` sidecars связаны SHA256
с исходной записью и архивом событий. Перед их выводом скрипт
[derive_recorded_contexts.py](../scripts/derive_recorded_contexts.py) восстановил
и проверил все **46 исходных context hashes**; portability не подменяет
оригинальные hashes. Повторная проверка без записи и без вызовов модели:

```bash
python3 -m scripts.derive_recorded_contexts \
  --directory baf/recordings \
  --captures docs/evidence/cp2-fixes/provider-record-smoke.jsonl \
  --events docs/evidence/cp2-fixes/provider-record-events.json --check
```

Проверка включена в CI/`check_all`. [Исходные capture-результаты](evidence/cp2-fixes/provider-record-smoke.jsonl)
и [события](evidence/cp2-fixes/provider-record-events.json) опубликованы отдельно
от исторической 117-run кампании. Capture прошёл **9/9**, сообщённый расход
**70 840 токенов**; это девять новых live-попыток для записи smoke, не девять
бесплатных replay и не дополнительные повторы полного базиса.

Playback имеет `provider=recorded-replay`, `quality_evaluation=false` и нулевой
новый расход токенов; исторический usage записи отражается отдельно. Смешение
live, synthetic и recorded provenance при агрегации отвергается. `check_all`
переключает только свой изолированный proxy после остальных replay-проверок,
не трогая пользовательский live stack и не используя API key.

## Validation status

Финальная приёмка выполнена на неизменной ревизии **`b117d62`**; SHA256 всех
119 проверяемых source-файлов на Ubuntu совпали с frozen manifest.

- **Ubuntu: 14/14 шагов PASS, cleanup PASS**, включая **225 offline tests**,
  реальные Docker limits/grading, WebDAV/SSH/FUSE, helper SIGKILL и оба настоящих
  manager/harness SIGKILL сценария: [summary](evidence/cp2-fixes/ubuntu/summary.json),
  [исходные артефакты](evidence/cp2-fixes/ubuntu/artifacts/).
- **Synthetic BAF 39/39** и **recorded smoke 9/9** прошли через реальный runtime.
  Все recorded строки имеют `provider=recorded-replay`; эти проверки не выдают
  replay за новое измерение качества модели.
- **Fedora: 225 offline tests PASS за 50.758 с**:
  [сохранённый отчёт](evidence/cp2-fixes/fedora-validation.json).
- **Actual-provider capture 9/9**, 46 ответов, **70 840 сообщённых токенов**;
  исходные девять записей сохранены без изменения байтов. Sidecars проверены
  восстановлением всех 46 исходных context hashes. [V2 audit](evidence/cp2-fixes/recorded-context-v2-audit.json)
  и [Docker диагностика порядка](evidence/cp2-fixes/recorded-enumeration-diagnostic.json)
  фиксируют узкие portability-исправления.
- GitHub [run 44693131644](https://github.com/r9zhenka/itmo-agent-runtime-track-a/actions/runs/44693131644)
  прошёл для старой ревизии `64ea82a`. Изменения до `b117d62` ещё не отправлены:
  **нового GitHub CI результата для них нет**. Локальная/Ubuntu-приёмка и GitHub
  Actions остаются разными источниками доказательств.

Исторические 169 tests и 117 live-попыток остаются в
[evidence/cp2](evidence/cp2/README.md). Два промежуточных неуспешных запуска
сохранены отдельно: [fixture failure](evidence/cp2-fixes/intermediate-failure/)
и [recording portability failure](evidence/cp2-fixes/recording-portability-failure/).
Они не удалены и не обозначены прошедшими после исправлений.

Для новой полной приёмки после подготовки Docker images, rclone, FUSE и sshd:

```bash
make test-ci
make check-all CHECK_ARGS=--existing-sshd
```

Проверки создают отдельный checkout/Compose project, очищают live-настройки и
используют только свои fixtures. `results/check-all/summary.json` содержит
результат каждого шага и cleanup, `artifacts/` — исходные отчёты. Успехом считается
полный отчёт с успешным cleanup; наличие отдельных файлов не доказывает успех
остальных шагов. Подготовка скачивает зависимости отдельно; сама приёмка не
обращается к внешнему LLM и не скачивает images. Подробнее:
[performance.md](performance.md#one-command-complete-offline-checks).

## Исправление самой crash-проверки при приёмке

Промежуточный Ubuntu запуск `results/check-all-cp2-fixes/summary.json` остановился
перед инъекцией отказа: `mkdtemp` создал probe-каталог с правами `0700` владельца
SSH user, тогда как менеджер работает как UID 0 с `cap_drop: ALL`. Без
`CAP_DAC_OVERRIDE`/`CAP_DAC_READ_SEARCH` он не мог проверить `.git` внутри чужого
закрытого каталога. Прямое воспроизведение показало `PermissionError` в
`SandboxManager.config`; обычные BAF-каталоги имели доступные для traversal права.
Это ошибка fixture теста, не отказ независимого watchdog.

Исправлен только checker: `fixture_directory` устанавливает `0755`, как у обычных
BAF fixtures, и сохраняет до 4096 байт диагностики нативного RPC вместо DEVNULL.
Новый offline regression проверяет права создаваемого каталога. Файл передан в
checkout `/home/bebra/.project-a-check-lpj7teqw` **до запуска crash-шага**, когда
полный synthetic BAF уже завершился, а выполнялся WebDAV шаг. Runtime/images и
сами ресурсы пользовательского stack не менялись. SHA256 исполняемого checker:
`66dc9e076f097cae7cebcda4b3e0882bd7177da014884e781b7c82d9703c27a4`.

Поэтому этот промежуточный запуск нельзя описывать как неизменную исходную копию
`0366b1c`: test-only patch зафиксирован коммитом `b37dedd` и учитывается в manifest. Исходный неуспешный
отчёт остаётся сохранённым. Повторный crash-шаг прошёл оба сценария. Полный suite затем упал на
recorded smoke, независимо от crash-проверки. Offline-счётчик внутри уже
начавшегося suite не включает добавленный после его старта тест: Ubuntu offline
base содержит 221, новый focused regression прошёл отдельно в составе 13
targeted tests. Полный Fedora запуск на этом этапе прошёл 222 tests.

Следующий промежуточный запуск дошёл до recorded smoke, но дал 7/9 из-за
порядка filesystem enumeration в B2.1/B9.1. После точного portability-исправления
`b117d62` выполнен **новый полный запуск из неизменной копии**: 225 offline tests,
все 14 шагов и cleanup прошли. В нём checker не заменялся во время исполнения.
[Финальное доказательство](evidence/cp2-fixes/ubuntu/summary.json).

## Что не заявляется исправленным

Нет полноценной POSIX-семантики WebDAV, атомарных конфликтов с локальным
редактором, durable session recovery, межпользовательской ОС-изоляции общего
SSH-аккаунта или гарантии cleanup при одновременной недоступности Docker и
control plane. Операции с неоднозначным эффектом после обрыва автоматически не
повторяются. Отдельный kernel VM даёт дополнительную границу, которую контейнер
сам по себе не предоставляет.

Исторические три неуспешные live-попытки остаются неуспешными. Инфраструктурные
фиксы и replay не повышают их оценки задним числом. Сравнение нескольких пар
модель/harness, выбор победителя и более широкие сценарии отказов остаются
отдельной работой ЧП3, а не условием признать каждый пункт текущей реализации
абсолютной гарантией.
