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
