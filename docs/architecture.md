# Architecture

## Цель

Система должна менять пароли, управлять ACL, VLAN и портами на смешанном парке оборудования, включая устройства без готовой поддержки Netmiko.

## Компоненты

1. Inventory
   - читает CSV/XLSX;
   - нормализует поля `vendor`, `model`, `ip_address`, `device_category`;
   - определяет драйвер по vendor/model.

2. Driver Registry
   - выбирает конкретный драйвер;
   - держит матрицу возможностей;
   - не зависит от транспорта.

3. Driver
   - генерирует фазовый `CommandPlan`;
   - знает режим конфигурации, сохранение конфига, особенности vendor CLI;
   - помечает secret-команды для redaction;
   - возвращает команды по фазам `exec`, `config`, `save`, `verify`.

4. Transport
   - подключается к устройству;
   - выполняет команды;
   - проверяет prompt и ошибки;
   - выбирается независимо от драйвера команд;
   - может быть заменен на Telnet/serial/API без изменения драйверов.

5. Orchestrator
   - строит dry-run;
   - читает/пишет JSON plan-file;
   - применяет изменения пачками;
   - снимает read-only backup конфигурации;
   - пишет аудит JSONL;
   - поддерживает stop-on-error, canary и лимиты размера пачки.

## Драйверы и транспорт

Netmiko может закрывать часть transport/prompt задач на известных платформах, но не заменяет продуктовую модель:

- vendor-specific операции остаются в скриптах;
- трудно сертифицировать нестандартные CLI;
- нет единого плана изменений и аудита;
- кастомные устройства вроде Bulat требуют своего драйвера.

В этой версии есть два SSH backend-а:

- Netmiko transport для платформ с устойчивой поддержкой `device_type`: `cisco_ios`, `huawei_vrp`, `hp_comware`, `hp_procurve`, `dell_powerconnect`, `eltex`;
- Paramiko prompt-driven transport для точных собственных драйверов и нестандартных CLI: Bulat, QTECH, D-Link/ограниченные профили, будущие локальные прошивки.

Вся логика CLI находится в собственных драйверах. Netmiko используется как транспорт там, где он действительно решает сессию и prompt, но не подменяет vendor-specific планы команд.

Лабораторная приемка драйверов описана в `docs/lab-validation.md`.

## Production roadmap

- Vault-интеграция для секретов;
- RBAC и approvals;
- web UI/API;
- scheduler и canary batches;
- rollback templates;
- session transcript storage;
- device facts discovery;
- драйверные golden tests по реальным выводам CLI;
- HA workers и очередь задач.
