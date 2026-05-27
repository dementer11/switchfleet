# NetOps Orchestrator

Каркас enterprise-системы для управления сетевым оборудованием через точные CLI-драйверы.

Что уже заложено:

- собственная модель драйверов CLI по семействам оборудования;
- dry-run планирование перед изменениями;
- SSH-транспорт с prompt-driven выполнением команд;
- операции смены паролей, ACL, VLAN и портов;
- read-only снятие backup running/current config;
- импорт инвентаря из CSV и Excel-экспорта;
- аудит плана и результата в JSONL;
- тесты на генерацию команд для разных CLI-семейств.

Поддержанные семейства на старте:

- Huawei VRP;
- Cisco IOS;
- HPE 1910/1920 Comware SMB;
- 3Com Comware legacy;
- HPE ProCurve/ArubaOS-Switch 2510/2530;
- Bulat BS, отдельный драйвер с обязательной лабораторной валидацией синтаксиса;
- Eltex MES;
- QTECH QSW;
- Dell PowerConnect;
- D-Link DES.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,xlsx]"
```

## Offline / Portable

Release assets include:

- `switchfleet-windows-offline-<version>.zip` - Windows offline installer with wheelhouse.
- `switchfleet-linux-offline-<version>.tar.gz` - Linux x86_64 offline installer with wheelhouse.
- `switchfleet-redos-7.3.6-offline-<version>.tar.gz` - RED OS 7.3.6 x86_64 offline installer with wheelhouse.
- `switchfleet-windows-portable-<version>.zip` - portable Windows bundle with embedded Python.

Offline installers do not use internet during installation. They require a local Python 3.10-3.13 x64 runtime.

Windows portable:

```powershell
.\switchfleet.cmd --help
```

Offline installers:

```powershell
.\install.cmd
.\switchfleet.cmd --help
```

```bash
./install.sh
./switchfleet --help
```

Проверить распознавание инвентаря:

```powershell
netops inventory ".\inventory.xlsx"
```

Сформировать dry-run план смены пароля:

```powershell
netops plan-password inventory.csv --username admin --new-password "NewSecret123!" --level admin
```

Сформировать dry-run план снятия конфигурации:

```powershell
netops plan-backup inventory.csv --limit 10
```

Снять backup с одного устройства:

```powershell
netops backup inventory.csv --login netadmin --password "CurrentPassword" --output-dir ".\backups" --limit 1
```

Запуск с реальным подключением требует учетные данные для входа:

```powershell
netops apply inventory.csv --login netadmin --password "CurrentPassword" --operation password --target-user admin --new-password "NewSecret123!"
```

## Важное ограничение

Команды для Bulat зависят от версии прошивки и режима CLI, а публичный CLI-мануал под BS2500/BS6300 не найден. Перед массовым применением нужен стендовый прогон на 1-2 устройствах каждого семейства и фиксация prompt/ошибок. Система специально разделяет генерацию команд и транспорт, чтобы быстро добавить уточненный драйвер под конкретную прошивку.
