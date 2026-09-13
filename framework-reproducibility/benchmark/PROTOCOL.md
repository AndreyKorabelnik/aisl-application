# Протокол независимого specification-only эксперимента

Версия 0.1; **scored run не разрешён до закрытия readiness gates**. Это порядок эксперимента, а не отчёт о его успехе.

## Модель и изоляция

Цель — последняя публично доступная DeepSeek на дату первого scored run. При запуске проверить официальный каталог/документацию, записать URL и дату, точный model ID, provider, доступный revision/snapshot, reasoning mode, context/output limits, temperature (если поддерживается), seed (если поддерживается), tools и бюджеты времени/токенов/итераций. Если модель доступна только по плавающему alias, сохранить ответ metadata и явно отметить ограничение воспроизводимости. Не выдавать текущую политику выбора за уже выбранную модель.

Один и тот же закреплённый model/config используется в первичном и одном повторном прогоне. Новая модель требует нового experiment ID. Параметры фиксируются до первого вызова и не подстраиваются после просмотра скрытых результатов. Сравнение с другой моделью не входит в текущую задачу.

Автор SDD читает F4.95. DeepSeek получает только выпущенный learner pack: спецификацию, разрешённые публичные schemas/contracts, синтетические открытые inputs и development tests. Ему не передаются Framework Source, recovery, source-derived reviewer inventory, существующие first-party wheels, hidden cases или oracle. Прямое копирование implementation snippets в SDD запрещено; алгоритмы объясняются независимо, публичные declarative contracts можно передавать с provenance.

Изолированное окружение предоставляет обычные средства разработки, компилятор/интерпретатор и заранее разрешённые сторонние библиотеки. Анализируемые приложения нельзя исполнять. Сеть в scored run выключена после подготовки dependencies; доступ к данным пользователя и Drive отсутствует. Реальные корпоративные архивы из текущего проекта не отправляются внешнему provider автоматически: сначала использовать синтетические fixtures.

## Readiness gates

1. Каждый MUST первого среза связан с exact contract, failure behavior, открытым примером и независимым acceptance case. Текущий draft этому ещё не соответствует.
2. Закрыты S01–S06 и принято явное решение по найденным contract issues S10/S11; отсутствуют обязательные TBD в learner package. Есть launch/build instructions, dependency policy, payload shapes и правила identity.
3. Canonical F4.95 выполняет открытый и скрытый corpus через production path; сохранены команды, exit codes, dependencies и raw outputs. Unit fixtures из исходных tests сами по себе не считаются end-to-end oracle.
4. Эквивалентность, допуски и обязательные assertions заморожены до передачи pack. Скрытые cases не выдаются модели, хранятся отдельно от learner artifact.
5. У evaluator нет зависимости от внутренних классов/таблиц альтернативной реализации. Black-box harness использует только договорённые CLI/HTTP/contracts.
6. Сохранены SHA learner pack, acceptance pack и точный model/config; запуск действительно specification-only.

## Выполнение

Первый прогон: чистая среда; DeepSeek строит runnable implementation по pack и может использовать открытые tests в пределах зафиксированного бюджета. Автор не добавляет подсказки, извлечённые из source, во время scored run. Неясности записываются в machine-readable questions log; если без ответа работа невозможна, прогон завершается как incomplete, а не получает тайное уточнение.

Модель сдаёт код, manifest зависимостей, запуск, протокол действий, известные ограничения. Отдельный evaluator выполняет held-out corpus и проверяет source → Core-like facts → knowledge → immutable revision → API → consumer. Наличие отдельных endpoints без работающей публикации не засчитывает цепочку.

Результат содержит coverage обязательств, количество pass/fail/not_run и отдельный перечень критических нарушений. Запрещено сводить ошибочное повышение confidence или чтение другой revision к незначительной потере среднего score. Порог перехода: все обязательные assertions выбранного среза проходят, нет critical violations; это не доказательство полного Framework coverage.

## Классификация failures и один повтор

- SPEC_GAP: требуемое поведение не определено.
- CONTRACT_AMBIGUITY: несколько допустимых прочтений.
- ACCEPTANCE_OVERFIT: тест проверяет внутреннюю реализацию вместо публичного поведения.
- MISSING_PUBLIC_CONTRACT: пользовательский путь требует недоступного контракта.
- HIDDEN_COUPLING: observable path зависит от неописанной связи компонентов.
- MODEL_IMPLEMENTATION_ERROR: требование однозначно, реализация его нарушает.
- INTENTIONALLY_UNSUPPORTED: случай заранее явно исключён; это не success для заявленной capability.

Исправления reviewer tooling/spec/acceptance остаются в side project. Найденный дефект Framework записывается, но не исправляется и не включается в новую canonical версию без отдельного решения. Баг baseline нельзя молча превратить в норму: отдельно решить compatibility requirement или documented exception до следующего прогона.

После доказанных исправлений выпустить новый immutable pack и выполнить один повтор с чистой сессией, закреплённой моделью и заранее подготовленным независимым holdout, чтобы не засчитать подгонку под раскрытые failures. После этого остановить эксперимент и решить, расширять ли scope до всего live Framework. Сам SDD-проект продолжает иметь конечную цель полного охвата, даже если пилот выявляет ограничения модели.

## Артефакты

`run-config.json`, hashes inputs, tool/prompt logs, learner questions, submitted implementation hash, evaluator raw outputs, assertion report и failure classification. Логи не должны содержать credentials. Скрытые inputs и oracle не включаются в learner ZIP; общий side-project checkpoint нельзя передавать модели целиком.

SP-SDD-0.1 содержит только протокол и заготовки проверки, без скрытого корпуса и без внешнего вызова DeepSeek.
