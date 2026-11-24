# 04. Прошивка, откат и спасение телефона

> Правило №1: **сначала полный бэкап через EDL**, потом любые записи в `boot`/`aboot`.

## Подготовка (до экспериментов)

1. Разрядите телефон не ниже 50 %.
2. Включите «USB-отладку», поставьте `platform-tools` в PATH.
3. Проверьте разблокировку загрузчика:

   ```powershell
   adb reboot bootloader
   fastboot getvar unlocked        # ожидается "unlocked: yes"
   fastboot oem device-info        # на части прошивок: Device unlocked: true
   ```

   Если `no` — сначала официальный Mi Unlock (заявка, 168 ч ожидания,
   привязка аккаунта). Без разблокировки LK не примет неподписанный boot.img.

4. Скачайте официальный fastboot-ROM именно для `ugg`/`ugglite` (тот, что
   соответствует вашей версии: Global/India). Внутри лежат:
   * `images\prog_emmc_firehose_8937_ddr.mbn` — программатор для EDL;
   * `images\boot.img`, `recovery.img`, `emmc_appsboot.mbn` — эталоны для отката.

## Уровни риска

| Действие | Риск | Восстановление |
|---|---|---|
| `fastboot boot <img>` | почти нулевой: ничего не пишется | зажать Power 10–15 с |
| `fastboot flash boot <img>` | средний: слот `boot` занят нашим образом | `fastboot flash boot stock_boot.img` |
| `fastboot flash aboot` | **высокий**: испорченный LK = кирпич без EDL | EDL + `prog_emmc_firehose_8937_ddr.mbn` |
| `fastboot erase persist`/`modemst*` | **критический**: теряются калибровки, IMEI | только бэкап |

Начинать всегда с `fastboot boot` — он не меняет флеш.

## Загрузка UEFI без записи

```powershell
powershell -ExecutionPolicy Bypass -File tools\probe.ps1 -Image build\boot-ugg.img
# или вручную:
fastboot boot build\boot-ugg.img
```

Выход из зависшего образа: **Power 10–15 с** (hard reset).

## Запись UEFI в слот boot (когда G1 пройден)

```powershell
# 1) сохранить стоковый boot (обязательно!)
adb shell su -c "dd if=/dev/block/bootdevice/by-name/boot of=/sdcard/boot_stock.img bs=1M"  # нужен root
# либо взять boot.img из fastboot-ROM — этого достаточно
copy images\boot.img build\boot_stock.img

# 2) прошить
fastboot flash boot build\boot-ugg.img
fastboot reboot
```

Откат:

```powershell
fastboot flash boot build\boot_stock.img
# или полный возврат к заводскому:
# запустить flash_all.bat из fastboot-ROM
```

## Если телефон не включается (чёрный экран, нет fastboot)

1. Зажать **Power + Vol- 15–20 с** — вход в fastboot. Если появился — `fastboot flash boot` стоковым.
2. Если fastboot нет: **EDL** — зажать **Power + Vol+ + Vol-** (или замкнуть
   тестовые точки) → в диспетчере устройств появляется `Qualcomm HS-USB QDLoader 9008`.
3. Прошить через EDL: `edl.py` (bkerler/edl) или `QFIL`/`MiFlash` с
   `prog_emmc_firehose_8937_ddr.mbn` из ROM. Команда для полного восстановления
   разделов — из `rawprogram0.xml`/`patch0.xml` того же ROM.
4. **Никогда** не стирайте `persist`, `modemst1/2`, `fsg`, `fsc` — это калибровки
   модема и сенсоров; при потере телефон «звонит», но IMEI/датчики мертвы.

## Что считать успехом каждого шага

| Шаг | Успех | Провал |
|---|---|---|
| probe G0 | экран мигает красный↔циан | чёрный экран/ребут → G0.1/G0.2 |
| G1 shell | видна UEFI-консоль | чёрный экран → проверить GIC/FD_BASE (см. 02) |
| G3 eMMC | `map -r` показывает блочные устройства | нет устройств → драйвер SDCC не готов |

## Полезные мелочи

* `fastboot getvar max-download-size` — ограничение на `fastboot boot`/`flash`
  (обычно 256 МиБ, нам хватает);
* `fastboot devices` пустой, а `adb devices` видит — телефон ещё в Android,
  сначала `adb reboot bootloader`;
* после записи своего boot.img проверка AVB может ругаться на «оранжевый экран»
  с предупреждением — это нормально при разблокированном BL.
