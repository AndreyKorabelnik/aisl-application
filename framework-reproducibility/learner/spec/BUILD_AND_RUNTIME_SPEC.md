# Сборка и запуск: контракт и открытые параметры

Статус: draft. Ниже задана требуемая граница; runnable reconstruction instructions ещё не завершены.

Четыре логические deployment boundaries: `aisl-producer`, `aisl-server`, `aisl-client`, `aisl-ui`. Они должны обслуживать производство knowledge, serving готовой AISL, программное потребление и пользовательский интерфейс соответственно. Не обязательно повторять приватную иерархию пакетов эталона.

Для пилота требуется рабочий путь producer → publication → server → client. Нельзя заявлять полную реконструкцию четырёх поставок, пока UI и весь функциональный охват не проверены.

Проверяемая установка должна описать версии языка, mature dependencies, команды сборки, параметры запуска, расположение state и очистку временного тестового state. Offline installability не обещается автоматически.

Parser baseline первого среза: `tree-sitter==0.26.0`, `tree-sitter-java==0.23.5`, `sqlglot==30.13.0`; structured OpenAPI fixture использует JSON. Для HOCON при расширении: `hocon-parser==1.13.0`. Выбор exact pins снижает расхождение грамматик; не требует повторения всех first-party package dependencies эталона.

Запрещены network access к оригинальному Framework, dependency на его first-party runtime в реконструированной реализации и загрузка recoveries. Зрелые third-party dependencies разрешены по зафиксированному списку. Корпоративные репозитории не передаются внешнему модельному сервису без отдельной проверки допустимости.

Наличие JSON Schema/API не заменяет полного протокола persistence, error behavior и запуска. Пока gaps S01–S06 открыты, этот документ не является обещанием воспроизводимой clean install.
