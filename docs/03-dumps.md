# 03. Какие дампы нужны и как их снять

Автоматически (без root) всё, что можно, снимает:

```powershell
powershell -ExecutionPolicy Bypass -File tools\collect-dumps.ps1
# -> dump\<серийник>\*.txt + manifest.txt
```

Ниже — что именно ищется и что делать с каждым файлом.

## 1. Идентификация SoC и DTB (самое важное)

```powershell
adb shell getprop ro.board.platform        # ожидается msm8937 / msm8940
adb shell getprop ro.product.device        # ugg (Prime) или ugglite
adb shell cat /proc/device-tree/compatible # реальный compatible
adb shell cat /proc/device-tree/model
adb shell cat /proc/device-tree/qcom,msm-id
```

Зачем: подтвердить, что это MSM8940 (а не MSM8917), и понять, какой dtsi
использовать (`msm8937.dtsi`, плата — `msm8937-*.dtsi`/`msm8940-*.dtsi`).

## 2. Память и cmdline от LK

```powershell
adb shell cat /proc/cmdline
adb shell cat /proc/meminfo
adb shell cat /proc/partitions
adb shell ls -l /dev/block/bootdevice/by-name
```

Что смотреть:
* `mem=` / `MemTotal` → реальный объём и раскладка RAM (для карты памяти UEFI);
* `androidboot.*`, `board_id`, `msm_id` → параметры платформы;
* размеры разделов → запас под UEFI (`boot` обычно 64 МиБ, хватит с запасом).

## 3. Загрузчик: `aboot` (нужен fastboot, разблокированный BL)

```powershell
adb reboot bootloader
fastboot getvar all > dump\fastboot_all.txt
fastboot getvar version-bootloader
fastboot oem device-info          # часть прошивок: unlock status
```

Если есть возможность прочитать раздел (root или EDL) — забрать `aboot`
и найти в нём строки:

```
strings aboot.img | findstr /i "aarch64 image boot_linux arm64 fastboot flash"
```

Наличие `AArch64`/`arm64`-кода и `boot_linux` с 64-битной ветвью = LK умеет
`Image`. Отсутствие — только 32-битная загрузка (см. G0.2).

## 4. Стоковый `boot.img` и DTB из него

Без root проще всего взять официальный fastboot-ROM для `ugg`
(`ugg_global_images_*.tgz`) и распаковать `boot.img`/`recovery.img`.

Либо с телефона, если есть root/TWRP:

```powershell
adb shell su -c "dd if=/dev/block/bootdevice/by-name/boot of=/sdcard/boot.img bs=1M"
adb pull /sdcard/boot.img dump\stock_boot.img
```

Из `boot.img` вытащить DTB (нужен для G0.1):

```powershell
python tools\extract_dtb.py dump\stock_boot.img -o build\stock.dtb
python tools\extract_dtb.py dump\stock_boot.img --scan    # если непонятно, что внутри
```

Скрипт разбирает legacy-заголовок (`dt_size`), ищет магию `D00DFEED` в ядре и в
образе целиком, проверяет `totalsize` и печатает `model=` для проверки глазами.

## 5. Дисплей и ввод (для консоли/кнопок)

```powershell
adb shell dumpsys display | findstr /i "width height density"
adb shell wm size
adb shell cat /proc/bus/input/devices      # какие есть кнопки/тач
```

Нужно, чтобы понять: сплэш 720×1280, каких кнопок ждать (Vol±/Power),
какой тач (для будущего SimpleInit-меню).

## 6. `persist`/`modemst*` — НЕ трогать

Перед любыми экспериментами: **сделать полный бэкап через EDL**, если есть
firehose-программатор `prog_emmc_firehose_8937_ddr.mbn` (лежит внутри
официального fastboot-ROM). Это единственный способ восстановить телефон,
если `aboot` или `persist` будут испорчены. См. `04-flash-recovery.md`.

## Что делать с результатом

Сложить `dump\<серийник>\` целиком и прислать. По ним:
1. фиксируются адреса в `fw/Silicon/Qualcomm/msm8937/Library/PlatformMemoryMapLib/PlatformMemoryMapLib.c`;
2. подтверждается/опровергается AArch64 (вместе с G0);
3. уточняется `FD_BASE/FD_SIZE` в `fw/configs/msm8937.conf`.
