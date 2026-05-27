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
   - генерирует CLI-команды;
   - знает режим конфигурации, сохранение конфига, особенности vendor CLI;
   - возвращает структурированный `CommandPlan`.

4. Transport
   - подключается к устройству;
   - выполняет команды;
   - проверяет prompt и ошибки;
   - может быть заменен на Telnet/serial/API без изменения драйверов.

5. Orchestrator
   - строит dry-run;
   - применяет изменения пачками;
   - снимает read-only backup конфигурации;
   - пишет аудит JSONL;
   - поддерживает stop-on-error и лимиты параллелизма.

## Почему не Netmiko

Netmiko решает часть transport/prompt задач, но не дает продуктовую модель:

- vendor-specific операции остаются в скриптах;
- трудно сертифицировать нестандартные CLI;
- нет единого плана изменений и аудита;
- кастомные устройства вроде Bulat требуют своего драйвера.

Здесь Netmiko не используется. SSH реализован отдельным адаптером поверх Paramiko, а вся логика CLI находится в собственных драйверах.

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
