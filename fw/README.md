# fw/ — скелет порта UEFI для MSM8937/8940 (ugg)

Это **не готовый UEFI**, а слой поверх [edk2-msm](https://github.com/edk2-porting/edk2-msm),
который добавляет поддержку SoC MSM8937/8940 и устройства Redmi Note 5A Prime.

## Что уже написано

| Файл | Состояние |
|---|---|
| `Silicon/Qualcomm/msm8937/Library/PlatformMemoryMapLib/*` | **готово**: карта DDR/MMIO из `msm8937.dtsi` |
| `Silicon/Qualcomm/QcomPkg/Library/MsmUartSerialPortLib/*` | **готово** (UART QUP v1.4, BLSP1_UART2), требует проверки на железе |
| `Platform/Qualcomm/msm8937/msm8937.dsc` | готово: GICv2, таймер 19.2 МГц, FD/heap/стек |
| `Platform/Qualcomm/msm8937/msm8937.fdf` | готово для G1 (Shell на framebuffer) |
| `Platform/Qualcomm/msm8937/dxe.fdf.inc` | **пусто**: перечислено, каких драйверов SoC не хватает |
| `Platform/Xiaomi/msm8937/ugg.dsc`, `ugg.fdf.inc` | готово (720×1280, dpi 320, ugg) |
| `Silicon/Qualcomm/msm8937/platform.sh.inc` | готово: BootShim + gzip(FD) + опциональный DTB |
| `configs/msm8937.conf`, `configs/devices/ugg.conf` | готово |
| `apply-overlay.ps1` | готово: накладывает слой на клон edk2-msm |

## Чего не хватает (по приоритету)

1. **SdccDxe** — драйвер eMMC (`sdhci@7824900`). Без него UEFI не видит разделы.
   В апстриме для этого SoC есть только закрытые бинари для других SoC.
2. **UsbInitDxe / UsbConfigDxe** — dwc3 + PHY (`0x078D9000`).
3. **DALTLMM** — GPIO (кнопки Vol±).
4. **SPMI / PmicDxe** — PMIC pmi8950 (pwrkey, LDO для eMMC/USB).
5. **ClockDxe** — GCC/RPM-клоки (нужны SDCC и USB).

Библиотеки `PlatformPeiLib`, `PlatformPrePiLib`, `MsPlatformDevicesLib`,
`SOCSmbiosInfoLib` в апстриме есть для `sdm660`; `apply-overlay.ps1` копирует их
с заменой имён, но **внутри есть жёстко прошитые адреса** — чек-лист печатается
в конце работы скрипта.

## Как наложить и собрать

```powershell
git clone --recurse-submodules --depth 1 https://github.com/edk2-porting/edk2-msm
powershell -ExecutionPolicy Bypass -File fw\apply-overlay.ps1 -Edk2Msm .\edk2-msm
cd edk2-msm
bash build.sh --device ugg --release DEBUG -t GCC5 -u
```

Подробно — `../docs/05-build.md`.

## Что даст первая сборка (G1)

`boot-ugg.img`, который на экране телефона показывает UEFI Shell: PrePi + DXE core
+ GICv2 + arch timer + `SimpleFbDxe` поверх сплэша LK. Это проверяет, что база
работает — и после этого можно писать драйверы SoC по одному.
