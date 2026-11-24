# 00. Железо: Xiaomi Redmi Note 5A Prime (`ugg`)

Всё ниже — либо из документации Qualcomm/DT, либо помечено **[проверить дампом]**.
Дампы снимаются `tools/collect-dumps.ps1`.

## Идентификация

| Параметр | Значение |
|---|---|
| Маркетинговое имя | Redmi Note 5A Prime (4/64 в вашем случае) |
| Кодовое имя | **ugg** (`ugglite` — это Redmi Note 5A на MSM8917, другой SoC) |
| SoC | **MSM8940** = Snapdragon 435; семейство MSM8937/8940 (SD430/435) |
| CPU | 8× Cortex-A53 (MSM8940 — до 1.4 ГГц), ARMv8-A, 64-бит **capable** |
| GPU | Adreno 505 |
| RAM / eMMC | 4 ГиБ / 64 ГиБ (у 4/64) |
| Экран | 5.5", 720×1280, ~320 dpi |
| Загрузчик | Qualcomm **LK / aboot** (`emmc_appsboot.mbn` в разделе `aboot`) |
| Штатный Android | 32-битный (armeabi-v7a) — SoC 64-битный, но userspace 32-бит |

Ключевой вывод из последней строки: **ядро и загрузчик исторически 32-битные**.
64-битные сборки на msm8937 существуют (XBL/LK умеют `Image`), но именно для
этого устройства это **не подтверждено** и проверяется пробой `tools/probe.ps1`.

## Цепочка загрузки

```
PBL (boot ROM, неизменяем)
  └─ XBL  (sbl1)         — инициализация DDR, часов, PMIC
      └─ aboot (LK)      — fastboot, выбор слота, проверка AVB, загрузка boot.img
          └─ boot.img    — kernel + [dtb] + [ramdisk]; LK прыгает в Image/zImage
              └─ Android init  …  или  НАШ UEFI (через BootShim)
```

`recovery` — отдельный раздел с той же структурой boot.img.
LK не является UEFI: он не умеет загружать `.efi` и не предоставляет UEFI-сервисы.
Поэтому UEFI-порт кладётся в `boot`/`fastboot boot` как **поддельное ядро**:

```
boot.img -> kernel = BootShim.bin + gzip(UEFI FD) [+ dtb]
```

`BootShim` (см. `fw` и апстрим `tools/BootShim/BootShim.S`) — это:
1. 64-байтный заголовок валидного arm64 `Image` (магия `ARM\x64` по смещению 0x38);
2. 2 инструкции `adr`/`b`;
3. код, который копирует FD по `UEFI_BASE` и прыгает туда.

## Карта памяти (из `msm8937.dtsi`, DDR 2 GiB вариант)

| Диапазон | Что |
|---|---|
| `0x80000000` | начало DDR; LK грузит `kernel` в `0x80008000` |
| `0x84A00000 +1E00000` | `other_ext` (reserved) |
| `0x86800000 +5000000` | `modem` (reserved) |
| `0x8B800000 +1100000` | `adsp_fw` (reserved) |
| `0x8C900000 +700000` | `wcnss_fw` (reserved) |
| `0x8D000000 +1000000` | **свободное окно** → сюда кладём UEFI FD (16 МиБ) |
| `0x8E000000 +1000000` | служебное: SEC heap, векторы, таблицы MMU, стек, Info Blk |
| `0x90000000 +1400000` | **`cont_splash_mem`** — сплэш LK, он же наш framebuffer |
| `0x92000000 …` | DDR heap DXE (по умолчанию 0x92000000 + 0x0D000000) |

Для 4 ГиБ RAM верхняя часть может быть выше `0x100000000` — **[проверить дампом]**
(`/proc/meminfo`, `/proc/iomem`, `mem=` в cmdline).

## MMIO (для драйверов)

| Блок | Адрес | Нужен для |
|---|---|---|
| GICv2 dist / cpu-if | `0x0B000000` / `0x0B002000` | прерывания |
| Arch timer / QTIMER | ARM generic + `0x0B120000` | таймеры |
| GCC (клоки) | `0x01800000` | всё, что работает с часами |
| TLMM (GPIO) | `0x01000000` | кнопки, USB-ID, UART-пины |
| SPMI | `0x0200F000` | PMIC pmi8950 (питание, pwrkey) |
| BLSP1 UART2 | `0x078B0000` | debug-консоль (если разведена) |
| SDHC1 (eMMC) | `0x07824900` | разделы, загрузка ОС |
| SDHC2 (microSD) | `0x07864900` | microSD |
| USB3 (dwc3) | `0x078D9000` | USB host/mass storage |
| MDSS | `0x01A00000` | панель (нам не обязательно — LK уже включил) |
| IMEM | `0x14680000` | SMEM/chipinfo |

## Разделы (типично для msm8937 Xiaomi)

Точный список — из `/dev/block/bootdevice/by-name` (дамп). Ожидаемо:
`gpt fsc qcsbl rpm tz hyp sec pmic sbl1 sbl1bak aboot abootbak boot recovery
system vendor cache misc persist modem fsg fsc keystore cmnlib cmnlib64 keymaster
devcfg dsp splash mdtp userdata` и т.п.

Что нам понадобится:
* `boot` — сюда/через fastboot boot попадает UEFI;
* `aboot` — для анализа: строки `AArch64`, `boot_linux`, `Image`, `fastboot flash`
  (по ним определяем, умеет ли LK в 64-бит);
* `splash`/`logo` — картинка сплэша;
* `persist`, `modemst*` — **никогда не трогать**, потеря = мёртвый IMEI/сенсоры.

## Требования LK к boot.img

* заголовок **v0** (`BOOTIMG_HEADER_VERSION=0`), страница 2048;
* kernel по `0x80008000`, tags по `0x80000100`, ramdisk по `0x81000000`;
* для arm64: магия `ARM\x64` по смещению 0x38 от начала kernel;
* DTB: **обязателен**. LK ищет подходящий DTB (`qcom,msm-id` + `qcom,board-id`)
  и без него отказывается грузить образ — см. раздел ниже.

## Подтверждено на живом устройстве (2026-11-24)

Проба `tools/probe.ps1` (серийник 2874661e, `dump/probe-getvar-2874661e.txt`):

| `getvar` | Значение | Что означает |
|---|---|---|
| `product` | **ugg** | это действительно Note 5A **Prime** |
| `kernel` | **lk** | загрузчик LK, не ABL/UEFI — как и ожидалось |
| `version` | 0.5 | версия LK |
| `variant` | MTP eMMC | eMMC (не UFS) → нужен SDCC-драйвер |
| `max-download-size` | `0x1ff00000` (~511 МиБ) | `fastboot boot` с нашим образом проходит |
| `secure` | yes | флаг secure boot LK; загрузку самописного образа это не заблокировало |
| `version-bootloader` | *(пусто)* | поэтому `getvar version-bootloader` падает — используйте `getvar all` |
| `partition-size:boot` | *(не выдаётся)* | размер слота `boot` уточнять через EDL/ROM |

Результат `fastboot boot` с нашим 120-байтным AArch64-образом:

```
Sending 'boot.img' (4 KB)              OKAY [  0.002s]
Booting                                FAILED (remote: 'dtb not found')
```

Три важных вывода:

1. **Загрузчик разблокирован** — образ принят (`Sending OKAY`), проверка подписи
   не сработала. Иначе ответ был бы `not allowed`/`signature`.
2. **AArch64 принимается**: LK распознал `Image` (магия `ARM\x64`) и дошёл до
   `boot_linux` — это уже половина ответа на вопрос G0.
3. **DTB обязателен**: без приложенного DTB (c `qcom,msm-id`/`qcom,board-id`
   этой платы) LK не стартует payload. Отсюда `tools/pull_devicetree.ps1`. 

## Framebuffer: измерено, а не угадано (2026-11-24)

Тестовые payload'ы (	ools/mkfbcal.py) с заливкой всего региона сплэша и
«счётными» линиями/рамкой дали однозначный результат:

| Параметр | Значение | Как получено |
|---|---|---|
| база |  x90000000 | заливка 8 МиБ делает экран ровно белым |
| bpp | **24 (RGB888)**, не 32 | ровные линии/рамка только в 24bpp-фазах |
| stride | **2160** = 720×3, без выравнивания | 2160 → ровно, 2176/2304/2880/2944 → диагонали |
| размер | 720×1280 | DTB панели 	m_otm1901a_720p_video |
| регион | splash_region 0x90000000 +20 МиБ | reserved-memory в uild/ugg.dtb |

Важно: у **ядра** (/sys/class/graphics/fb0) другие параметры — 32bpp и
stride 2944. Это ЕГО собственный буфер (dmesg: mdss_mdp_splash_init: splash
memory reserve failed), к сплэшу LK он отношения не имеет. Ориентироваться на
sysfs при настройке UEFI нельзя.

Следствие для порта: SimpleFbDxe из edk2-msm не подходит (он 32-битный),
поэтому написан свой Silicon/Qualcomm/msm8937/Drivers/UggFbDxe
(GOP 720×1280, конвертация 32bpp BGRA → 3 байта, PCD PcdFbStride/PcdFbRgbOrder).

Порядок каналов (RGB или BGR) пока не подтверждён цветным тестом — для
чёрно-белой UEFI-консоли это не важно; проверить перед SimpleInit/GRUB.