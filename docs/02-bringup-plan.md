# 02. План bring-up: G0 → G6

Каждый шаг — это «воронка»: если шаг не прошёл, дальше идти нельзя, иначе
непонятно, что именно сломано. Ничего не прошивается, пока не пройден G0.

## G0. Есть ли AArch64? (2 минуты, без записи на флеш)

```powershell
powershell -ExecutionPolicy Bypass -File tools\probe.ps1
```

Payload: образ 120 байт (заголовок arm64 Image + 56 байт кода), заливает экран красным ↔ цианом (~3 Гц), вечный цикл.

**Статус на 2026-11-24 (реальный прогон, серийник 2874661e):**

```
Sending 'boot.img' (4 KB)   OKAY [  0.002s]
Booting                     FAILED (remote: 'dtb not found')
```

Это не провал G0: LK распознал наш AArch64-`Image` (магия `ARM\x64`) и дошёл до
`boot_linux`, а загрузчик разблокирован (иначе было бы `not allowed`).
Осталась одна мелочь — приложить DTB (G0.1) и повторить.

| Что на экране | Вывод |
|---|---|
| мигает красный/циан | **PASS**: LK входит в AArch64, FB = `0x90000000`. Идём в G1 |
| `dtb not found` | нужен DTB → G0.1 (на ugg он обязателен) |
| ничего / логотип / ребут | G0.1, затем G0.2 |
| мигает, но «мусор»/полосы | AArch64 работает, неверен формат пикселя — фиксируем 32bpp |

### G0.1. DTB (на ugg обязателен)

Быстрый путь — собрать DTB из живого Android (без скачивания прошивки):

```powershell
fastboot reboot                                                   # вернуться в Android
powershell -ExecutionPolicy Bypass -File tools\pull_devicetree.ps1
powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Dtb build\stock.dtb
```

Резервный путь — DTB из стокового `boot.img` (см. `03-dumps.md`):

```powershell
python tools\extract_dtb.py dump\stock_boot.img -o build\stock.dtb
powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Dtb build\stock.dtb
```

Если LK и с DTB говорит `dtb not found` — не совпали `qcom,msm-id`/`qcom,board-id`:
нужен именно стоковый DTB из `boot.img` этой ревизии, а не реконструированный.

### G0.1a. Что выяснилось на практике (LK и формат DT)

Проверено на устройстве:

* LK **игнорирует** поле `dt_size` в legacy-заголовке: образ с корректным DTB
  (`msm-id 0x139`, `board-id 0x8`) и `dt_size>0` всё равно даёт `dtb not found`.
* LK принимает образ, если kernel — это **`gzip(kernel) + весь DT-блок стока`**
  (в стоковом `boot.img` после gzip-потока лежат два DTB подряд: MSM8917-MTP и
  MSM8940-MTP, ~643 КБ). Такой образ отвечает `Booting OKAY`.
* Значит «DTB» для сборки — не один `.dtb`, а **хвост стокового kernel**:
  `python tools\extract_dtb.py <boot.img> --dtblock -o build\ugg.dtblock`.

Сборка пробы по этой схеме уже вшита в `probe.ps1` и `mksmoke.py`
(`--gzip --append build\ugg.dtblock`), если файл `build\ugg.dtblock` существует.

### G0.2. Если и с DTB тишина

Три гипотезы, в порядке проверки:

1. **LK 32-битный** (не умеет `Image`) — тогда нужен arm32-payload.
   Быстрый тест: payload с магией zImage (`0x016f2818` по смещению 0x24) вместо
   `ARM\x64`; если экран ожил — порт надо делать на **EDK2 ARM** (AArch32).
2. **FB не по `0x90000000`** — проверить `cont_splash_mem` в вашем DTB
   (в G0.1 можно поменять адрес в `tools/mksmoke.py`, константа `FB_ADDR`).
3. **LK запрещает fastboot boot** (проверка подписи) — тогда только запись в
   `boot` (см. `04-flash-recovery.md`), что уже рискованно.

## G1. UEFI Shell на экране (первый настоящий UEFI)

Собрать `boot-ugg.img` (см. `05-build.md`), залить:

```powershell
fastboot boot build\boot-ugg.img
```

Критерий: на экране появляется UEFI-консоль (или меню SimpleInit), видно
строки `Renegade Project` / `UEFI Interactive Shell`.

Что это доказывает: PrePi + DXE core + GICv2 + Timer + SimpleFbDxe работают на
этом SoC. Драйверов SoC для этого не нужно.

Типичные причины чёрного экрана на этом шаге (по убыванию частоты):
* `FD_BASE`/`FD_SIZE` не совпадают с картой памяти → BootShim копирует в занятую область;
* неверные PCD GIC (для 8937 это **GICv2**, не GICv3) → зависание до консоли;
* `SimpleFbDxe` не получил геометрию (720×1280) или сплэш уже погашен LK;
* BootShim не смог декомпрессировать/скопировать FD (`FD_SIZE` больше реального образа).

## G2. Логи по UART (опционально, но снимает 80 % боли)

Если на плате есть debug-UART (обычно 3 площадки под экраном, 1.8 В):
собрать с `-u`, подключить USB-UART 1.8 В, увидеть `SEC`/`PEI`/`DXE` лог.

Без UART дальше придётся отлаживать «по цвету экрана»: в коде можно рисовать
стадии загрузки (закрасить полосу после PrePi, после DXE, после GIC и т. д.).
Это медленно, но работает.

## G3. eMMC: увидеть разделы

```text
Shell> map -r
Shell> ls fs0:\
```

Критерий: виден FAT-раздел (обычно `persist`/`modem`/`userdata` — не FAT;
скорее всего увидите `fs0` только после того, как появится FAT на microSD).

Блокер: **нужен драйвер SDCC**. План:

1. Взять за основу SDHCI-совместимый host controller (регистры стандартные,
   `SDHCI_CAPABILITIES` по смещению 0x40) — `sdhci-msm` в Linux как справочник;
2. Проверить, что после LK eMMC запитано: чтение `SDHCI_PRESENT_STATE` должно
   дать осмысленные биты, а `SDHCI_CAPABILITIES` — ненулевой;
3. Реализовать `EFI_SD_MMC_PASS_THRU` + подключить `MdeModulePkg/Bus/Sd/EmmcDxe`
   и `MdeModulePkg/Universal/Disk/{DiskIo,Partition}Dxe` + `FatPkg`.
4. Если питание снято — понадобится SPMI/PMIC (LDO) и RPM-клоки, это отдельная
   большая задача.

## G4. Загрузить Linux с раздела eMMC

`LinuxLoader`/`GRUB` + ядро из `boot`. Критерий: ядро стартует, виден
`console`-вывод (через framebuffer simplefb).

## G5. microSD / USB

* microSD: тот же SDHCI-драйвер, второй экземпляр (`0x07864900`);
* USB: dwc3 + PHY (host mode) → `UsbMassStorageDxe` → загрузка с флешки.

## G6. «Любая система»

GRUB/SimpleInit + ISO-образ на microSD/USB. Это уже полноценный UEFI-сценарий.

## Журнал работ (заполнять по мере прохождения)

| Шаг | Дата | Результат | Комментарий |
|---|---|---|---|
| G0 | 2026-11-24 | PASS | LK входит в AArch64; образ с gzip+DT-блоком грузится, экран управляется |
| G0.5 | 2026-11-24 | PASS | геометрия FB: 24bpp, stride 2160, база 0x90000000 |
| G1 | | | |
| G2 | | | |
| G3 | | | |
