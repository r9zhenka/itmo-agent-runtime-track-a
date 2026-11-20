# ЧП2: ответы по текущему проекту A

Материал соответствует [вопросам второго чекпоинта](https://github.com/deeppavlov/agentic-course-itmo/blob/main/projects/checkpoint-2-questions.md).
Это отдельный документ: пользовательские ответы первого чекпоинта
`answers-task-a.md` не изменены. Подробная [схема](cp2-architecture.md),
[разбор двух трейсов](cp2-trace-walkthrough.md) и [статус](checkpoint-status.md)
разделяют опубликованные доказательства и последующие исправления.

**Граница доказательств.** Историческая кампания на `9555ba9` дала 109/117
исходных и 114/117 после проверяемого исправления чекеров; клиент `ea39ddc`
отдельно прошёл C3 3/3. Их исходные данные не переписаны. Для актуального
**`b117d62` Ubuntu прошла все 14 шагов и cleanup**, включая 225 offline tests,
39/39 synthetic BAF и 9/9 recorded smoke, из неизменной копии с совпавшими
119 source hashes: [summary](evidence/cp2-fixes/ubuntu/summary.json).
[Fedora225](evidence/cp2-fixes/fedora-validation.json) прошёл за 50.758 с.
Отдельные live smoke captures — 9/9, 70 840 токенов. Промежуточные fixture и
portability failures сохранены в [истории исправлений](cp2-fixes.md).
GitHub CI [успешен только для `64ea82a`](https://github.com/r9zhenka/itmo-agent-runtime-track-a/actions/runs/44693131644);
изменения до `b117d62` ещё не отправлены, нового GitHub run нет.

## Общие вопросы

**1. Что изменилось после ЧП1?** Появилось реальное монтирование Fedora → Ubuntu VM,
квоты экспортера, независимый watchdog, полный набор 39 задач, скрытый Docker-грейдер,
единая offline-приёмка, измерения и первая live-кампания. Новые исправления после
аудита добавляют session ownership, прогресс sandbox, retention закрытых сессий,
mount guard и усиленные проверки сбоев. Что уже запускалось, а что ждёт проверки,
отмечено в [статусе](checkpoint-status.md) и [отчёте](cp2-report.md).

**2. Какой запуск показывает текущее состояние?** Для воспроизводимой инфраструктуры
— `make check-all CHECK_ARGS=--existing-sshd` на Ubuntu после подготовки образов,
rclone и FUSE. Финальная ревизия `b117d62`, все 14 шагов и cleanup прошли:
[сохранённый summary](evidence/cp2-fixes/ubuntu/summary.json). Историческая проверка
описана отдельно в [отчёте](cp2-report.md#acceptance-evidence). Для качества — 117 попыток
первой пары с [manifest](evidence/cp2/cp2-manifest.json), исходными и исправленными
[результатами](evidence/cp2/README.md). Исторические параметры: три повтора, три
параллельные сессии, 100 млн токенов как потолок, резерв 4 млн на in-flight run;
свежий прогон на изменённом коде является другим экспериментом.

Команда исторической кампании на клиенте, с кодом `9555ba9` на обеих машинах
и моделью/лимитами из [manifest](evidence/cp2/cp2-manifest.json):

```bash
python3 -m scripts.benchmark \
  --ssh-host project-a-ubuntu \
  --ssh-config /home/r9zhenka/.ssh/config \
  --server-repo /home/bebra/itmo-agent-runtime-track-a \
  --repeats 3 --parallel 3 \
  --pair custom+deepseek-v4.1-flash-1017 \
  --token-budget 100000000 --run-token-reserve 4000000 \
  --output results/live-cp2.jsonl
```

Это описание уже выполненного запуска, не команда перезаписи evidence. Повторный
эксперимент использует новый output: runner добавляет строки. На сервере были
`LLM_MODE=live`, `LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash-1017`, max_tokens=2048,
model timeout=90 с, run timeout=600 с и max_steps=16; effort остался provider
default без независимого подтверждения. Provider key остаётся в серверном `.env`,
client token передаётся конфигурацией/окружением, не указан в команде. 55 source
hashes manifest привязывают параметры к исходному коду; эта команда на новой
ревизии не воспроизводит старую последовательность ответов стохастической модели.

**3. Существенная проблема и доказательство?** Клиент ждал 210 с при серверном
бюджете 600 с, отменив C3 повтор 2. В серверном seq 51 видны `cancelled` и
210432.511 мс; исходная строка раннера содержит ошибку ожидания. Связь подтверждена
отдельным [аудитом восстановления](evidence/cp2/live-cp2-reconciliation-audit.json),
а [разбор](cp2-trace-walkthrough.md) объясняет, какие выводы следуют из событий.

**4. Какие решения пересмотрены?** Нельзя отождествлять unittest только со stderr,
внешний exit shell-обёртки — с exit дочерней программы, и удаление контейнера самим
тестом — с самостоятельностью watchdog. Поэтому чекеры исправлены с uniform
regrade, новый crash acceptance ждёт отдельный сервис, а клиент сохраняет частичные
метаданные. К защите нужны дополнительные пары и анализ свойства базиса; ограничения
FUSE/конкурентного редактора и границы отказа контроллеров остаются явными.

## Клиент, gateway, сессии — A1–A4

**A1. Один запрос от подключения до очистки.** RemoteClient экспортирует папку,
SSH-helper запускает mount guard и создаёт gateway-сессию; сообщение запускает
цикл модели/инструментов; клиент читает SSE; release завершает сессию и снимает
монтирование. [Диаграмма последовательности](cp2-architecture.md#сессия-монтирование-обрывы-и-отмена)
показывает ресурсы; [B1.1 seq 1–12](cp2-trace-walkthrough.md#успех-b11-повтор-1)
показывает настоящий агентный цикл. Cleanup подтверждается отдельной приёмкой,
поскольку в историческом агентном трейсе нет отдельного события unmount.

**A2. Авторизация и папка.** GUI/CLI используют Bearer token, проверяют health-identity
сервера, затем создают сессию для выбранной папки. Для удалённого режима нужны
проверенный SSH host key и export token; неверный токен даёт auth error, недоступный
сервер — transport error. HTTP redirects отклоняются. Код:
[client API](../client/api.py), [remote client](../client/remote.py),
[HTTP boundary](../runtime/common.py).

**A3. Роль gateway и чужие сессии.** Gateway проверяет токен, определяет principal,
сопоставляет session_id с владельцем и проверяет все RPC/SSE. `CLIENT_TOKEN`
обозначает default; `CLIENT_IDENTITIES_JSON` задаёт дополнительные токены.
Create-request ID отделён по principal. Это изоляция API-сессий: общий SSH/host
account и доступные ему папки не превращаются в раздельных OS tenants.
[Код](../runtime/gateway.py), [ADR сессий](adr/0006-sessions.md).

**A4. Переподключение.** Клиент продолжает `events` с последнего `seq`; повторное
чтение не повторяет инструменты. Сохраняются in-memory события удерживаемой сессии.
После eviction закрытой сессии или restart процесса история недоступна. Протоколы
и replay-cursor проверки описаны [здесь](protocols.md#client--server).

## Харнес, модель, инструменты — A5–A10

**A5. Агентный цикл.** `Harness.message` создаёт run, `Harness.run` вызывает модель,
валидирует и выполняет tool_calls, добавляет результаты в контекст и повторяет шаг.
Ответ без tool_calls завершает run. Отмена, критическая ошибка, бюджет времени,
16 шагов или context cap также останавливают его. [Код](../runtime/harness.py),
[ветвления на схеме](cp2-architecture.md#путь-сообщения-и-условия-завершения).

**A6. Контекст и длинный вывод.** История содержит SYSTEM, user, assistant и tool
messages. Вывод контейнера ограничен 64 KiB на stdout и stderr с `truncated`;
serialized context более 180 000 символов приводит к ошибке. Автоматической
компрессии и обещания вместить произвольную историю нет. [Harness](harness.md),
[Docker logs adapter](../runtime/docker_engine.py).

**A7. Диспетчеризация.** Имя/аргументы проверяются по [TOOLS](../runtime/contracts.py).
Для каждой операции создаётся ID run-step-call. `Remote.execute` отправляет `start`
менеджеру, читает operation events и возвращает результат в контекст. Харнес не
импортирует subprocess/Docker; команда запускается Docker Engine в sandbox.
Файловые инструменты тоже работают внутри контейнера.

**A8. Зачем LLM-прокси?** Он изолирует provider key и формат API, выбирает модель/режим,
возвращает usage и ограничивает ошибки. Для новых запросов transport различает
HTTP status, timeout/transport, invalid response и finish reason без публикации
секретных bodies/headers. Старые трейсы этих новых полей не получают задним числом.
[Proxy](../runtime/llm_proxy.py), [transport](../runtime/provider_transport.py),
[конфигурация модели](model-eligibility.md).

**A9. Неверные аргументы и лимиты.** Ошибки аргументов и ненулевой command exit
возвращаются модели для корректировки. Ошибка провайдера, критический transport/
sandbox error, timeout/cancel и исчерпание шагов завершают run с отличным от success
исходом. Успех run ещё не означает правильность BAF-ответа: её определяет чекер.
[Ошибки и повторы](protocols.md#idempotency-and-retry-policy).

**A10. Замена харнеса/модели.** `HARNESS_URL` задаёт совместимую реализацию харнеса;
LLM_MODE/LLM_MODEL/LLM_PROVIDER_URL/LLM_EXTRA_JSON задают прокси. Пока реализован один
харнес. При сравнении фиксируются задачи, число попыток, prompts/tool schemas,
сандбокс, ресурсы, mounts, лимиты, параллелизм и модель/effort. Полная сравнительная
матрица относится к ЧП3, [ADR оценки](adr/0008-evaluation.md).

## Монтирование — A11–A15

**A11. Путь файла.** Локальная папка → клиентский WebDAV → обратный SSH-forward →
server-loopback endpoint → host rclone/FUSE → Docker bind `/work`. В sandbox сети
нет; файл проходит через host filesystem. [Схема](cp2-architecture.md#машины-процессы-контейнеры-и-данные),
[инструкция двух машин](remote-mount.md).

**A12. Почему этот механизм?** Экспортер позволяет напрямую ограничить выбранную
папку без SSH-сервера на клиенте. Рассмотрены SSHFS/SFTP и NFS/WireGuard, а copy/sync
не выполняет требование mount. Цена — FUSE-настройка, ограниченные POSIX-семантики
и много round trips для мелких файлов. [Сравнение](adr/0005-mounting.md#alternatives),
[измерения](cp2-report.md#measured-performance).

**A13. Видимость и конфликты.** Acceptance проверяет чтение клиентских файлов,
запись обратно и видимость последующей локальной правки. Новые parent/child locks
не дают открыть пересекающиеся экспорты; PUT/MOVE/DELETE повторно проверяют версии
и ETag preconditions. Последнее окно между проверкой и мутацией для локального
редактора остаётся: полноценного распределённого lock нет.
[Exporter](../client/workspace_server.py), [ADR](adr/0005-mounting.md).

**A14. RO/RW и защищённые пути.** Режим действует в экспортере, FUSE и Docker bind.
Directory-FD операции запрещают выход через симлинки, hard links и служебные пути,
включая `.git`. Remote export имеет квоту 256 MiB/4096 entries. Local RW — только
явный trusted-development opt-in, без aggregate quota; он защищает только
существующий верхний `.git`, в отличие от remote export.
[Граница hardening](hardening.md), [файловый инструмент](../runtime/file_tool.py).

**A15. Обрыв монтирования.** Потеря lease даёт transport failure и прекращает
операцию. Самостоятельный mount guard обрабатывает EOF helper-pipe, отзывает lease,
останавливает rclone и unmount. Отдельная реальная Ubuntu helper-SIGKILL проверка
прошла три проверки и включена в финальный успешный acceptance. Исторический
disconnect pass не подменяет этот результат. Новое соединение создаёт
новый mount/session; неоднозначная запись автоматически не повторяется.
Guard/host failure может потребовать ручной cleanup. [Lifecycle](cp2-architecture.md).

## Сандбокс, протоколы, сбои — A16–A21

**A16. Менеджер и sandbox.** Менеджер — доверенный control plane с Docker socket;
provision резервирует workspace, start принимает инструмент, events возвращает
progress/result, collect отдаёт метаданные, release очищает и освобождает резерв.
Sandbox — отдельный непривилегированный command-container. Состояние shell между
операциями не сохраняется. [Контракт](protocols.md#harness--sandbox).

**A17. Лимиты и очистка.** По умолчанию 1 CPU, 256 MiB RAM без дополнительного swap,
64 PIDs, tmpfs 64 MiB, file-size limit 128 MiB, remote aggregate quota и deadline.
Resource probes ограниченно исчерпывают CPU/RAM/PIDs/диск. Новый crash acceptance
убивает только проверенные disposable Compose controllers и требует лог отдельного
watchdog для manager loss. Старый тест вызывал reaper сам, поэтому этой гарантии
не доказывал. [Hardening](hardening.md), [новый тест](../scripts/check_watchdog_crash.py).

**A18. Привилегии и секреты.** Sandbox UID/GID не равны нулю, root FS read-only,
capabilities dropped, no-new-privileges, network none. Provider/client/internal
токены, SSH key и Docker socket туда не передаются. Папки разных сессий не должны
пересекаться. Manager/watchdog с Docker socket и ядро хоста остаются доверенными;
API principals не обещают изоляцию владельцев одного SSH account.
[Docker acceptance](../scripts/docker_check.py) проверяет non-root, network,
secrets и bind boundaries; [offline isolation regressions](../tests/test_runtime.py)
проверяют резервирование workspace, [export-conflict tests](../tests/test_workspace_conflicts.py)
— parent/child overlap. Статус реальных запусков отделён в [отчёте](cp2-fixes.md#validation-status).

**A19. Схемы и инварианты.** Машиночитаемые JSON Schema лежат в [contracts](../contracts),
обе границы описаны в [протоколах](protocols.md). start/events сохраняет cursor и
ровно один terminal operation result; одинаковый ID с тем же payload не выполняет
операцию повторно. Сроки ограничены на RPC и command. Idempotency сохраняется только
в пределах живого процесса и retention сессии, не после restart/eviction.

**A20. Классы ошибок и повтор.** `command` — exit !=0; `timeout` — бюджет;
`sandbox` — контейнер/Docker; `transport` — связь/потеря lease. Исправление команды
может предложить модель. Повтор чтения событий безопасен; side-effect RPC требует
сверки прежнего ID. Новый ID после потерянного ответа способен повторить запись.
[Таблица ошибок](protocols.md#idempotency-and-retry-policy).

**A21. Отмена и гонки.** GUI/CLI → gateway owner-check → Harness.cancel →
SandboxManager.cancel → force-remove дерева контейнера. Терминальную отмену
публикует только путь, подтвердивший cleanup; ошибка cleanup не выдаётся за clean
cancel. При гибели контроллера deadline/lease независимо проверяет watchdog.
Записанные файлы не откатываются. [Код](../runtime/harness.py),
[сценарии сбоев](cp2-architecture.md#сессия-монтирование-обрывы-и-отмена).

## Трейсы, проверки, БАФ — A22–A26

**A22. Успешный и неуспешный трейс.** [Разбор B1.1 и C3](cp2-trace-walkthrough.md)
указывает session/run IDs, seq, инструменты, результаты, время и токены. В B1.1
финал seq12 success/3663 tokens; в C3 seq51 cancelled/72490 known tokens. Причина
210-секундной отмены подтверждается клиентской ошибкой и серверным событием вместе.
Полные provider request payload исторически не сохранялись; неизвестное не выдумано.

**A23. Что работает в CI без внешней сети?** В опубликованном
[run 44693131644](https://github.com/r9zhenka/itmo-agent-runtime-track-a/actions/runs/44693131644)
прошли offline и docker jobs. Подготовка скачивает инструменты/образы заранее;
`make check-all` затем использует локальные/bridge/SSH связи, synthetic replay и
реальный Docker/FUSE. Unit/CLI сценарии используют mock/fixture executor и сами
не доказывают изоляцию. Новые правки прошли полную Ubuntu-приёмку, но ещё не
отправлены в GitHub и не имеют нового Actions run; режимы
настоящих сохранённых model-recordings учитываются отдельно от synthetic replay.
Сейчас сохранены девять actual-provider записей (capture 9/9, 70 840 токенов).
Playback — `LLM_MODE=recorded`, provider `recorded-replay`, новые tokens=0,
quality=false. Девять SHA256-bound sidecars `project-a-observation-v2` выводятся только
после проверки всех 46 original contexts. Игнорируется metadata начального `ls -la`;
только для exact task/command сортируются три grep-записи B2.1 и два find-пути B9.1.
Имена, содержимое, типы/размеры файлов, число/кратность записей, иной порядок,
последующий output и ошибки остаются значимыми; raw recordings не меняются.
`derive_recorded_contexts --check` включён в CI. Финальная Ubuntu-проверка
`b117d62` прошла все 14 шагов, recorded9/9 и cleanup. Предыдущий failed run
(7/9 из-за B2.1/B9.1 enumeration order) сохранён; он не заменён успешным задним
числом. [Финальный summary](evidence/cp2-fixes/ubuntu/summary.json).
[Workflow](../.github/workflows/project-a.yml), [метод](performance.md),
[записи и воспроизведение](cp2-fixes.md#recorded-smoke).

**A24. Полный базис первой пары.** 24 задачи курса + 8 оригинальных вариантов + 3 B9
+ 4 composites = 39; три свежие попытки каждой = 117. Есть независимые фикстуры/чекеры,
53 скрытых тестовых входа для задач генерации кода и [сырые данные](evidence/cp2/README.md).
[Матрица](live-results.md): 114/117 после проверяемой переоценки, исходные 109/117 сохранены.
Это первая пара, а не готовый сравнительный выбор победителя.

**A25. Чья ошибка в провалах?** B2.1 #1 — этап провайдера, но историческая ошибка
слишком общая для конкретной транспортной причины. B5.4 #2 — неправильный тип ответа
модели (`healthy=false` вместо `2`). C3 #2 — жизненный цикл клиента с коротким ожиданием.
Пять ложных отказов вызваны чекерами stdout/stderr/capture и исправлены без повторных
model calls. [Доказательства и аудит](evaluation-corrections.md).

**A26. Какие измерения и выводы?** По 10 повторов: stat, дерево, 32 мелких файла,
чтение большого файла и запись с close через настоящий mount; запуск контейнера
из готового образа, полный цикл exec и память cgroup. Медианы/p95 и исходные
измерения в [отчёте](cp2-report.md#measured-performance).
Например, пакет 32 × 4 KiB читается через mount за медианные 1,735 с; полный цикл
команды занимает медианные 0,602 с. p95 при n=10 — максимум; разные машины, кэши и
версии Python мешают приписать всю разницу одному механизму. Полные дополнительные
затраты памяти Docker на хосте не измерены.
Дополнительные пары и более строгие сравнения остаются следующими проверками.
