# Статус проекта (UGG UEFI)

Документ фиксирует, что уже проверено **на реальном устройстве**, а что
осталось. Все проверки — воспроизводимые сборки в CI (`build-uefi.yml`),
патчи лежат в `fw/patches/`, инструменты — в `tools/`.

## Достигнуто (G1 — UEFI на экране)

Цепочка загрузки проверена целиком:

```
PBL → XBL → LK/aboot → boot.img (BootShim + gzip(FD) + DT-блок стока)
    → PrePi (наш минимальный пролог) → DXE-ядро → драйверы → BdsDxe → консоль
```

На экране телефона выводятся (подтверждено фото):

```
Ugg UEFI  MSM8940  Redmi Note 5A Prime
TianoCore/EDK2 firmware version e195262
Press any side button for SimpleInitGUI
```

| Компонент | Статус | Чем подтверждено |
|---|---|---|
| LK принимает `boot.img` | ✓ | `fastboot boot` → `Booting OKAY` |
| BootShim + gzip(8 МиБ) + DT-блок | ✓ | отдельный тест: 3 полосы после копирования |
| PrePi (наш минимальный пролог) | ✓ | стадии 1–5 |
| DXE-ядро | ✓ | диспетчеризация доходит до BDS |
| `CpuDxe` | ✓ | шаги 1–8 после отключения NX/RO-политик |
| дисплей 720×1280, 24 bpp, stride 2160, сдвиг −256 | ✓ | «крест»: пиксель в пиксель |
| `GOP` + `Blt` | ✓ | белый квадрат, нарисованный через `Blt` |
| свой `SimpleTextOut` (шрифт 8×12) | ✓ | три строки текста на фото |
| `BdsDxe` + консоль UEFI | ✓ | вывод версии и приглашения |

## Найденные причины (почему раньше не работало)

1. **Порядок FV**: `VariableRuntimeDxe` и `DevicePathDxe` стояли после консоли
   и BDS — консольные драйверы упирались в отсутствующие переменные.
2. **Защита памяти DXE** (`PcdDxeNxMemoryProtectionPolicy`,
   `PcdImageProtectionPolicy`): при установке CPU-протокола ядро начинало
   применять NX/RO-политику, что вешало `CpuDxe`.
3. **`SyncCacheConfig`** в `CpuDxe` зацикливался на нашей карте памяти
   (обход страничных таблиц) — отключён в `fw/patches/cpudxe_fix.py`.
4. **`SerialPortLib`** в роли `FrameBufferSerialPortLib` печатал в 24-битный
   framebuffer как в 32-битный — отсюда «мусорный текст» на весь экран.
5. **`BdsDxe` не запускался** при выключенных HII/UI: лечится форсированием
   однократного запуска драйверов (`fw/patches/force_dispatch.py`).
6. **`ConSplitter` не подключал `GraphicsConsole`** к нашему GOP: `ConOut`
   существовал, `OutputString` возвращал успех и ничего не рисовал. Решение —
   своя реализация `SimpleTextOut` в `UggFbDxe` + `ConnectController`.

## Состав прошивки

Профили переключаются `tools/set_fdf_profile.py`:

* `min` (17 компонентов) — ядро, память/переменные, консоль, GIC/таймер,
  наш драйвер дисплея, `BdsDxe`;
* `min disk services smbios` (30) — **рабочая конфигурация**: плюс дисковый
  стек, сервисы (capsule/reset/RTC/status code) и SMBIOS;
* `+ hii` — меню настроек (требует HII);
* `+ logo/shell/simpleinit` — приложения (Shell и SimpleInit нуждаются в вводе;
  `UiApp` без HII падает с исключением).

## Что осталось

### 1. eMMC (SDCC1) — главный блокер загрузки

Из device tree (`tools/dtb_node.py build/ugg.dtb sdhci`):

```
узел:   /soc/sdhci@7824900
base:   0x07824900 (hc_mem 0x500), 0x07824000 (core_mem 0x800),
        0x07824E00 (cmdq_mem 0x200)
irq:    0x7B (hc), 0x8A (pwr)
шина:   8 бит, nonremovable  → это eMMC
клоки:  iface_clk, core_clk, ice_core_clk
частоты: 400k … 384 МГц, режимы HS400/HS200/DDR 1.8 В
```

Что уже измерено на устройстве:

| Проба | Результат |
|---|---|
| SDHCI CAPABILITIES (0x40) | `0x342DCB02` — контроллер живой, SDHCI-совместим |
| PRESENT_STATE (0x24) | `0x01F80000` — шина не занята |
| CLOCK_CONTROL (0x2C) | `0x0007` — клок был включён LK |
| Software Reset / Power | проходят (`reset: OK`, `power: OK`) |
| **CMD0** (GO_IDLE_STATE) | **TIMEOUT**, при этом `int status = 0`, `err status = 0` |
| вендорский блок 0x100… | почти весь нули |

Вывод: LK держит контроллер в **своём (не SDHCI) режиме**, вендорский слой
SDCC не инициализирован, поэтому команды «не выходят». Нужно:

1. поднять клоки `sdcc1_iface_clk`/`sdcc1_apps_clk` через GCC (0x01800000);
2. инициализировать вендорские регистры SDCC (режим, DLL, задержки);
3. пройти инициализацию eMMC: CMD0 → CMD1 → CMD2 → CMD3 → CMD9 → CMD7 →
   CMD8/CMD6 (ширина 8 бит, HS200/HS400) → CMD17/18 для чтения;
4. реализовать `EFI_BLOCK_IO_PROTOCOL` → поверх него уже работают
   `PartitionDxe` и `Fat`.

Оценка: это основная часть работы по порту (недели итераций), потому что
каждый шаг проверяется только на устройстве.

### 2. Ввод (кнопки)

Из device tree (`tools/dtb_keys.py build/ugg.dtb`):

| Кнопка | Источник |
|---|---|
| VOL+ | TLMM GPIO 91 (по DT), **на практике не подтверждено** |
| VOL− | PMIC PON (`pon_2`), linux,code = 114 |
| POWER | PMIC PON (`pon_1`), linux,code = 116 |

Проверено: чтение пина 91 не меняется при нажатии; запись в его CFG роняет
систему (пин занят). Чтение всех 122 пинов тоже приводит к перезагрузке —
значит «перебором» пины трогать нельзя.

Правильный путь: **SPMI-транзакции к `pm8937`** (PON) → два кнопки сразу,
включая POWER. После этого — `SimpleTextInputEx` (POWER = Enter, VOL± = выбор).

### 3. Загрузчик

После eMMC: `LinuxLoader`/GRUB как EFI-приложение в FV + ядро и rootfs
(Alpine/postmarketOS для msm8937). Загрузка возможна и без ввода, если
сделать авто-запуск первого пункта.

## Реальные ограничения (озвучены сразу)

* **Windows на ARM не заработает**: нет ACPI-таблиц и драйверов под этот SoC.
* UEFI-порт исследовательский: апстрим edk2-msm не поддерживает msm8937/8940,
  драйверы SoC (включая eMMC) пишутся с нуля.
* Linux-дистрибутивы — реалистичная цель; ядро msm8937 в mainline есть, но
  требует своего DT и настройки.

## Инструменты

| Файл | Назначение |
|---|---|
| `tools/audit_patches.py` | проверка всех патчей против **закреплённой** версии edk2 |
| `tools/set_fdf_profile.py` | профили состава FV (`min`, `disk`, `hii`, `usb`, `apps`…) |
| `tools/gen_font.py` | генерация шрифта 8×12 из системного шрифта Windows |
| `tools/uncomment_fdf.py` | возврат выключенных компонентов FDF |
| `tools/dtb_keys.py` | кнопки из device tree |
| `tools/dtb_node.py` | произвольные узлы DT (eMMC, клоки и т. п.) |
| `tools/list_fv_order.py` | фактический порядок файлов в FV |
| `tools/test_size.py`, `test_bootshim.py`, `test_fd_stub*.py` | проверки загрузки и точек входа |
| `tools/decode_guid_barcode.py` | расшифровка GUID драйвера по фото экрана |

## eMMC (G3): журнал измерений

Все значения сняты на устройстве через драйвер дисплея (текстовый вывод).

### Базовые адреса (из device tree, `tools/dtb_node.py build/ugg.dtb sdhci`)

```
/soc/sdhci@7824900   compatible = "qcom,sdhci-msm"
  hc_mem   0x07824900 (0x500)
  core_mem 0x07824000 (0x800)
  cmdq_mem 0x07824E00 (0x200)
  irq      0x7B (hc), 0x8A (pwr)
  bus-width 8, nonremovable  -> eMMC
  clock-names: iface_clk, core_clk, ice_core_clk
```

### Что показал контроллер

| Регистр | Значение | Смысл |
|---|---|---|
| SDHCI CAPABILITIES (hc+0x40) | `0x342DCB02` | контроллер живой, SDHCI-совместим |
| PRESENT_STATE (hc+0x24) | `0x01F80000` | шина не занята |
| CLOCK_CONTROL (hc+0x2C) | `0x0007` | клок был включён LK |
| MCI_VERSION (core+0x50) | `0x10000040` | major=1, minor=0x40 |
| MCI_HC_MODE (core+0x78) | было `0`, стало `1` | **SDHCI-режим был выключен**; мы его включаем (бит 0), плюс бит 13 = FF_CLK_SW_RST_DIS |
| PWRCTL_STATUS (core+0x0DC) | `0x00000002` | **BUS_OFF** — питание карты не подано |
| SDHCI SW_RESET (hc+0x2F) | self-clear OK | сброс проходит |
| CMD0 / CMD1 | TIMEOUT, int/err status = 0 | команды не исполняются, пока шина обесточена |

### Вывод

Порядок для eMMC: **сначала питание (vdd/vdd-io через PMIC/RPM), затем SDHCI init, затем команды**.
Без питания контроллер держит BUS_OFF и не отправляет команды (ни complete, ни error).

### Опорные источники (найдены и изучены)

* `msm8916-mainline/lk2nd` — `platform/msm_shared/{sdhci.c,sdhci_msm.c}`, `include/sdhci_msm.h`:
  последовательность init LK, `SDCC_MCI_HC_MODE`, регистры DLL/CDC.
* `WOA-Project/Lumia950XLPkg/Driver/SdhciMMCHSDxe` — **полный UEFI-драйвер**
  SDHCI/eMMC с `EFI_BLOCK_IO_PROTOCOL` (`mmc_sdhci.c` 70 КБ, `sdhci.c`,
  `sdhci_msm.c`, `MMCHS.c`, `SdhciMMCHS.inf`). Готовый образец для порта.
* Из его `Shared.dsc.inc` — смещения регистров питания:
  `MCI_HC_MODE=0x78`, `PWRCTL_STATUS=0xDC`, `PWRCTL_MASK=0xE0`,
  `PWRCTL_CLEAR=0xE4`, `PWRCTL_CTL=0xE8`.
* Из `Include/Platform/iomap.h` — раскладка GCC для SDCC1:
  `SDCC1_BCR=CLK_CTL+0x4C0`, `SDCC1_APPS_CBCR=+0x4C4`, `SDCC1_AHB_CBCR=+0x4C8`,
  `SDCC1_CMD_RCGR=+0x4D0`, `SDCC1_CFG_RCGR=+0x4D4`, `SDCC1_M=+0x4D8`,
  `SDCC1_N=+0x4DC`, `SDCC1_D=+0x4E0` (значения для msm8994; для msm8937
  смещения надо уточнить по downstream-ядру).

### Следующие шаги (по порядку)

1. Поднять питание eMMC: vdd и vdd-io (`vdd-supply`/`vdd-io-supply` из DT).
   Это PMIC/RPM-путь; после него PWRCTL_STATUS должен показать BUS_ON (бит 0).
2. Проверить клоки GCC (`apps_clk` для SDCC1) — если apps_clk не идёт,
   команды уйдут «в никуда» даже при питании.
3. Портировать `SdhciMMCHSDxe` как `UggSdccDxe`: инициализация eMMC
   (CMD0/1/2/3/9/7/6/8), ширина 8 бит, HS200, затем `EFI_BLOCK_IO_PROTOCOL`.
4. На выходе: `PartitionDxe` + `Fat` увидят разделы, и станет возможна
   загрузка Linux (`LinuxLoader`/GRUB + ядро + rootfs).

### Уточнение после пробы питания (mode 11)

| Проверка | Значение | Вывод |
|---|---|---|
| PWRCTL_STATUS до | `0x00000002` | BUS_OFF (шина обесточена) |
| запись `MCI_POWER` (core+0x0) = `0x03` | читается `0x00` | запись не держится |
| PWRCTL_STATUS после | `0` затем `0x00000002` | BUS_ON не появляется, возврат в BUS_OFF |
| CMD0 после подачи питания | TIMEOUT, `int status = 0` | команды не исполняются |

**Вывод:** питанием eMMC управляет не контроллер, а PMIC/RPM (регулятор vdd/vdd-io).
SDCC только сообщает состояние шины. Значит следующий обязательный блок —
**SPMI + RPM: включение регулятора eMMC**, и лишь затем SDHCI-инициализация карты.

Замечание: `MCI_HC_MODE` (core+0x78) записывается и читается корректно,
то есть доступ к `core_mem` рабочий; не работает именно регистр питания —
это ожидаемо, т.к. реальное напряжение подаёт PMIC.

### Порядок работ по eMMC (обновлённый)

1. SPMI-транспорт к `pm8937` (контроллер SPMI: база из памяти SoC, IRQ) —
   научиться читать регистры PMIC (проверка: чтение `PON`/`REVID`).
2. Регулятор eMMC: vdd (2.95 В) и vdd-io (1.8 В) — включить, дождаться
   стабильного напряжения.
3. Убедиться, что PWRCTL_STATUS показывает BUS_ON.
4. Клок `apps_clk` для SDCC1 через GCC (если ещё не идёт).
5. Портировать `SdhciMMCHSDxe` (готовый UEFI-драйвер, ссылка выше) как
   `UggSdccDxe`: CMD0→CMD1→CMD2→CMD3→CMD9→CMD7→CMD6/CMD8, 8 бит, и
   `EFI_BLOCK_IO_PROTOCOL`.
6. `PartitionDxe` + `Fat` → появляются разделы и файлы.

## SPMI (PMIC): журнал измерений и выводы

Попытки выполнить транзакцию к PMIC приводили к **мгновенной перезагрузке**
устройства (watchdog), поэтому режимы 16 и 18 в боевой сборке не включаются.

### Что подтверждено (безопасные чтения)

| Что | Значение |
|---|---|
| версия арбитра (core+0x0) | `0x20018000` — Arbiter v2 |
| регион `cnfg` (0x0200A000), таблица mapping (+0x0B00) | `0x002E0701` — читается |
| окна `chnls` (0x02400000) / `obsrvr` (0x02C00000) | `0x080004B0` — читаются |
| путь по дереву PPID→канал для PPID=0 | `0 → 3 → 0x32 → 0x61 → 0x6E → 0x85 → 0x8C → 0x8D → 0x90` |
| **канал PMIC top (ppid 0)** | **`0x72`** |
| формат команды | `(opc << 27) \| (offset << 4) \| (byte_count - 1)`, `EXT_READ = 13` |

Проверка разбора таблицы: переходы полностью совпадают с полями записей
(`002E0701` → bit11=0 → idx=3; `00266504` → bit9=0 → idx=0x32;
`0022C333` → bit8=0 → idx=0x61), то есть алгоритм верный.

### Что НЕ работает

* `CONFIG = 0` в окне канала (отключение IRQ-режима, как в LK `spmi.c`) —
  добавлено, не помогло;
* запись `CMD` в `chnls + 0x8000*chan` → **система уходит в перезагрузку**;
* вариант адресации из LK (`SPMI_BASE + 0xF800 + chan*0x80`) относится к
  арбитру v1 и для нашего железа (v2) не подходит.

### Гипотезы для следующего захода

1. **Блок SPMI не тактируется/не выведен из сброса** для APSS после LK:
   проверить/включить ветки клоков SPMI в GCC (аналогично SDCC1: RCG + CBCR,
   ждать `ROOT_OFF`), затем повторить транзакцию.
2. **Владелец канала (EE/owner) не наш**: RPM/APSS могут владеть каналом;
   тогда нужна запись в ownership table (`cnfg + 0x0700`) или обмен правами.
3. **Проверить альтернативную таблицу `REG_CHNL`** (core + 0x800): каждая
   запись кодирует `sid<<16 | pid<<8` для канала `i`. Наш канал 0x72 можно
   подтвердить по этой таблице — если он там отсутствует, значит разбор
   дерева всё же расходится с железом.

### Практический вывод

SPMI — необходимый, но «глухой» блок: без него нет ни питания eMMC
(`BUS_OFF`), ни кнопок (PON). Всё остальное уже работает и проверено:
UEFI грузится, дисплей и текст работают, BDS доходит до приглашения,
дисковый стек и SMBIOS собраны.
