# Доказанное наблюдение, требующее решения до scored run

## S10: orientation несимметричного JOIN operator

F4.95 Core на `SELECT a.id FROM event a JOIN validity b ON b.start_time > a.event_time;` возвращает pair:

`left=event.event_time`, `right=validity.start_time`, `operator=>`, `predicate=b.start_time > a.event_time`, status confirmed.

При чтении pair как `left operator right` получается обратное неравенство относительно predicate. Producer ориентирует стороны по JOIN rowsets, но сохраняет исходный operator. Это подтверждено реальным вызовом штатного Core owner; raw result в `oracles/reversed-range-observation.json`, source SHA в CONTRACT_PROBES.

Основной код НЕ исправлялся. Не объявлять это поддержанным корректным semantic behavior. Возможные решения: зафиксировать bug-compatible opaque pair + authoritative predicate или отдельно исправить Framework и явно перебазировать SDD/oracle. Решение не принято; S10 блокирует scored assertion для reversed inequality, но не мешает продолжению остальных контрактов. Автоматическая инверсия только в comparator скрыла бы дефект и запрещена.

## S11: разные JOIN projections

В SP-SDD-0.3 реальный ASGI API после Runner/Core/KLC/bundle import подтвердил различие: `/sql/joins` сохраняет expression_links; `/sql/query-context` не включает это поле в joins. Raw парное сравнение — `oracles/pipeline/join-projection-comparison.json`. Source/schema и runtime observation согласованы. Это endpoint-specific контракт, не blanket defect API; его описание закрыто в API_READBACK_CONTRACT. Нельзя считать один Core output точным oracle всех API.

## Ограничения исполненных probes

Исторические 0.2 Core SQL/builder probes: 16 assertions PASS, без Runner/KLC/server. Новые 0.3 diagnostic pipeline probes: 50 assertions PASS, включая реальные процессы Core/KLC, neutral builder/importer и ASGI API. High-level KCP planning/publication adapter и внешний TCP server не исполнялись, поэтому S01/S06 не закрыты целиком. Ни один corporate repository не передавался внешней LLM; использованы только открытые синтетические Java/OpenAPI/SQL inputs.
