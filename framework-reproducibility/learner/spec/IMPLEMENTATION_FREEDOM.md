# Свобода реализации и запрещённые обходы

Можно менять число внутренних packages/classes, алгоритмы и структуры данных, если сохраняются observable contracts, ownership boundaries и их acceptance. Более простая совместимая реализация является успешным результатом.

Нельзя:

- читать или устанавливать исходную реализацию Framework;
- хардкодить ответы под открытый corpus;
- угадывать missing schema/relation/attribute/placeholder;
- превращать unknown/partial в confirmed;
- заменять зрелый parser regexp fallback;
- создавать вторую таблицу истинности capabilities или tool registry вне заданного owner;
- подменять exact revision на active/latest;
- восстанавливать удалённый reporting lifecycle;
- считать PASS по открытым примерам доказательством всей функциональности.

Совместимость с целевым pinned контрактом не равна поддержке исторических контрактов. Backward compatibility, aliases и dual-read не требуются.

Internal artifact bytes и physical DB schema не обязаны совпадать, если они не зафиксированы как public transport/input contract. Для каждой внешней границы reviewer обязан заранее определить, что именно сравнивается.
