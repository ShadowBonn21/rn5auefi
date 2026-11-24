# 05. Как собрать UEFI

Локально нужно: Linux-среда (WSL2/Docker) с `gcc-aarch64-linux-gnu`, `uuid-dev`,
`iasl`, `python3`, ~8 ГБ свободного места. На этой машине свободно 4.9 ГБ,
поэтому основной путь — **CI** (`.github/workflows/build-uefi.yml`).

## Вариант A: GitHub Actions (рекомендуется)

1. Создать репозиторий, залить эту папку.
2. Actions → `build-uefi-ugg` → Run workflow.
3. Скачать артефакт `ugg-uefi` (`boot-ugg.img`, `*.fd`).

Что делает workflow: клонирует `edk2-msm` с сабмодулями, копирует библиотеки
`sdm660 → msm8937`, накладывает `fw/`, собирает `--device ugg -t GCC5 -u`.

## Вариант B: WSL2 / Ubuntu 22.04

```bash
sudo apt update && sudo apt install -y \
  build-essential gcc-aarch64-linux-gnu uuid-dev iasl nasm \
  python3 python3-pip git gzip gettext

git clone --depth 1 --recurse-submodules --shallow-submodules \
  https://github.com/edk2-porting/edk2-msm.git ~/edk2-msm
cd ~/edk2-msm
```

Наложить порт (из Windows-папки проекта):

```powershell
# PowerShell на Windows, путь к клону внутри WSL — \\wsl$\Ubuntu\home\<user>\edk2-msm
powershell -ExecutionPolicy Bypass -File fw\apply-overlay.ps1 -Edk2Msm "\\wsl$\Ubuntu\home\<user>\edk2-msm"
```

Или вручную (как в CI):

```bash
for lib in PlatformPeiLib PlatformPrePiLib MsPlatformDevicesLib SOCSmbiosInfoLib; do
  cp -r Silicon/Qualcomm/sdm660/Library/$lib Silicon/Qualcomm/msm8937/Library/
  find Silicon/Qualcomm/msm8937/Library/$lib -type f -exec sed -i 's/sdm660/msm8937/g; s/SDM660/MSM8937/g' {} +
done
cp -r <проект>/fw/Silicon/Qualcomm/msm8937/. Silicon/Qualcomm/msm8937/
cp -r <проект>/fw/Silicon/Qualcomm/QcomPkg/Library/MsmUartSerialPortLib Silicon/Qualcomm/QcomPkg/Library/
mkdir -p Platform/Qualcomm/msm8937 Platform/Xiaomi/msm8937
cp -r <проект>/fw/Platform/Qualcomm/msm8937/. Platform/Qualcomm/msm8937/
cp -r <проект>/fw/Platform/Xiaomi/msm8937/.   Platform/Xiaomi/msm8937/
cp <проект>/fw/configs/msm8937.conf configs/
cp <проект>/fw/configs/devices/ugg.conf configs/devices/
```

Сборка:

```bash
bash build.sh --device ugg --release DEBUG -t GCC5 -u     # DEBUG + UART-логи
# результат: ./boot-ugg.img, ./workspace/uefi-ugg-kernel
```

`DEBUG` даёт подробный лог (в UART и, частично, на экран). Для «тихой» сборки:
`--release RELEASE`.

## Вариант C: Docker

```bash
docker run --rm -it -v "$PWD":/w -w /w ubuntu:22.04 bash
# далее как в варианте B
```

## DTB (для G0.1 и для LinuxLoader)

В апстриме boot.img собирается с приложенным DTB
(`Platform/<vendor>/<soc>/FdtBlob_compat/<device>.dtb`). У нас его нет:

```powershell
python tools\extract_dtb.py dump\stock_boot.img -o build\stock.dtb
copy build\stock.dtb <clone>\Platform\Xiaomi\msm8937\FdtBlob_compat\ugg.dtb
```

После этого `platform.sh.inc` из `fw/` сам приложит DTB к образу.
Можно и не прикладывать — тогда LK передаст свой, а UEFI/ядро возьмёт его из
`x0`/`chosen` (см. `LinuxLoader`).

## Частые ошибки сборки

| Ошибка | Причина |
|---|---|
| `EDK2 not found` | не инициализированы сабмодули |
| `Device configuration not found` | нет `configs/devices/ugg.conf` |
| `SoC configuration not found` | нет `configs/msm8937.conf` |
| `Module ... not found` в FDF | не хватает SoC-бинарей (ожидаемо: см. `fw/Platform/Qualcomm/msm8937/dxe.fdf.inc`) |
| `gcc-aarch64-linux-gnu not found` | не установлен кросс-тулчейн |
| падение на `SimpleInit` | не собран rootfs: `gettext`/`msgfmt` отсутствует, либо `--skip-rootfs-gen` |

## Что считается «собранным»

* `boot-ugg.img` ≤ 64 МиБ (иначе не влезет в раздел `boot`);
* `MSM8937_UEFI.fd` — сам UEFI-образ (можно `fastboot boot` только в составе boot.img);
* в `Build/ugg/DEBUG_GCC5/FV/` лежат `.efi` компоненты — по ним видно, что реально вошло.
