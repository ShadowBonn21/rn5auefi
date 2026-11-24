/** @file
  SerialPortLib для Qualcomm BLSP UART (QUP v1.4 / "uartdm") на MSM8937.

  Порт: BLSP1_UART2 @ 0x078B0000 (msm8937.dtsi: serial@78b0000), 115200 8N1,
  такт 19.2 MHz. На retail-устройствах Xiaomi этот UART обычно НЕ разведён и
  не инициализирован — поэтому все ожидания ограничены счётчиком, а не "вечно":
  иначе DebugLib на мёртвом UART подвесил бы загрузку.

  Регистры соответствуют Linux drivers/tty/serial/msm_serial.c (uartdm).
  ВАЖНО: если на вашей ревизии другой QUP (GENI, v2) — нужен другой драйвер;
  проверяется по /proc/device-tree/... compatible = "qcom,msm-lsuart-v14".

  SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Base.h>
#include <Library/BaseLib.h>
#include <Library/IoLib.h>
#include <Library/SerialPortLib.h>
#include <Library/PcdLib.h>

/* ── база порта: переопределяется PCD gQcomTokenSpaceGuid.PcdUartBaseAddress ── */
#ifndef MSM_UART_BASE
#define MSM_UART_BASE 0x078B0000
#endif

/* uartdm v1.4 */
#define UARTDM_MR1   0x0000
#define UARTDM_MR2   0x0004
#define UARTDM_SR    0x00A4
#define UARTDM_CR    0x00A8
#define UARTDM_IMR   0x00B0
#define UARTDM_ISR   0x00B4
#define UARTDM_TF    0x0100
#define UARTDM_RF    0x0140

/* SR bits */
#define UARTDM_SR_RX_READY  BIT0
#define UARTDM_SR_TX_READY  BIT2
#define UARTDM_SR_TX_EMPTY  BIT3

/* CR bits */
#define UARTDM_CR_RST_RX    BIT1
#define UARTDM_CR_RST_TX    BIT2

#define SPIN_LIMIT  200000U   /* ~ единицы мс на Cortex-A53; защита от зависания */

STATIC
UINTN
UartBase (
  VOID
  )
{
  return (UINTN)MSM_UART_BASE;
}

STATIC
BOOLEAN
UartWaitSr (
  IN UINT32  Mask
  )
{
  UINTN  Base = UartBase ();
  UINTN  i;

  for (i = 0; i < SPIN_LIMIT; i++) {
    if ((MmioRead32 (Base + UARTDM_SR) & Mask) != 0) {
      return TRUE;
    }
    ArmNopFence ();
  }
  return FALSE;
}

/**
  Инициализация порта.

  Ничего не переконфигурирует по скорости: рассчитывает на то, что LK/предыдущая
  ступень уже настроили 115200 8N1 (так делает debug-сборка aboot).
  Делает безопасный минимум: сбрасывает FIFO и глушит прерывания.

  @retval RETURN_SUCCESS  всегда (порт может быть физически мёртв — это не фатально).
**/
RETURN_STATUS
EFIAPI
SerialPortInitialize (
  VOID
  )
{
  UINTN  Base = UartBase ();

  MmioWrite32 (Base + UARTDM_IMR, 0x7F);           /* все прерывания выключены */
  MmioWrite32 (Base + UARTDM_CR, UARTDM_CR_RST_RX | UARTDM_CR_RST_TX);

  /* чтение ISR снимает флаги; результат не нужен */
  (VOID)MmioRead32 (Base + UARTDM_ISR);

  return RETURN_SUCCESS;
}

/**
  Записать буфер в UART. Не блокируется дольше SPIN_LIMIT на символ.

  @param  Buffer  данные
  @param  NumberOfBytes  сколько байт

  @return сколько байт принято портом
**/
UINTN
EFIAPI
SerialPortWrite (
  IN UINT8  *Buffer,
  IN UINTN  NumberOfBytes
  )
{
  UINTN  Base = UartBase ();
  UINTN  i;

  if ((Buffer == NULL) || (NumberOfBytes == 0)) {
    return 0;
  }

  for (i = 0; i < NumberOfBytes; i++) {
    if (!UartWaitSr (UARTDM_SR_TX_READY)) {
      break;                                     /* UART не отвечает — не виснем */
    }
    MmioWrite32 (Base + UARTDM_TF, (UINT32)Buffer[i]);
  }

  return i;
}

/**
  Прочитать байты, если они есть.

  @return число прочитанных байт (0, если пусто)
**/
UINTN
EFIAPI
SerialPortRead (
  OUT UINT8  *Buffer,
  IN  UINTN  NumberOfBytes
  )
{
  UINTN  Base = UartBase ();
  UINTN  i;

  if ((Buffer == NULL) || (NumberOfBytes == 0)) {
    return 0;
  }

  for (i = 0; i < NumberOfBytes; i++) {
    if ((MmioRead32 (Base + UARTDM_SR) & UARTDM_SR_RX_READY) == 0) {
      break;
    }
    Buffer[i] = (UINT8)(MmioRead32 (Base + UARTDM_RF) & 0xFF);
  }

  return i;
}

/**
  Есть ли что читать.

  @retval TRUE  в FIFO есть байт
**/
BOOLEAN
EFIAPI
SerialPortPoll (
  VOID
  )
{
  return (MmioRead32 (UartBase () + UARTDM_SR) & UARTDM_SR_RX_READY) != 0;
}

/**
  Настроить параметры линии.

  Реализация консервативная: подтверждает только 115200 8N1 (то, что ставит LK).
  Для других скоростей нужно программировать IPR/MR2 под такт 19.2 MHz —
  TODO: см. msm_serial.c::msm_set_termios.

  @retval RETURN_SUCCESS      115200 8N1 принято
  @retval RETURN_UNSUPPORTED  иные параметры
**/
RETURN_STATUS
EFIAPI
SerialPortSetAttributes (
  IN OUT UINT64              *BaudRate,
  IN OUT UINT32              *ReceiveFifoDepth,
  IN OUT UINT32              *Timeout,
  IN OUT EFI_PARITY_TYPE     *Parity,
  IN OUT UINT8               *DataBits,
  IN OUT EFI_STOP_BITS_TYPE  *StopBits
  )
{
  if ((BaudRate != NULL) && (*BaudRate != 115200)) {
    return RETURN_UNSUPPORTED;
  }
  if ((Parity != NULL) && (*Parity != NoParity)) {
    return RETURN_UNSUPPORTED;
  }
  if ((DataBits != NULL) && (*DataBits != 8)) {
    return RETURN_UNSUPPORTED;
  }
  if ((StopBits != NULL) && (*StopBits != OneStopBit)) {
    return RETURN_UNSUPPORTED;
  }
  if (ReceiveFifoDepth != NULL) {
    *ReceiveFifoDepth = 32;
  }
  return RETURN_SUCCESS;
}

/**
  Управляющие линии (DTR/RTS) на BLSP UART не используются.
**/
RETURN_STATUS
EFIAPI
SerialPortSetControl (
  IN UINT32  Control
  )
{
  return RETURN_UNSUPPORTED;
}

/**
  Состояние управляющих линий: сообщаем "готов" и "есть данные".
**/
RETURN_STATUS
EFIAPI
SerialPortGetControl (
  OUT UINT32  *Control
  )
{
  if (Control == NULL) {
    return RETURN_INVALID_PARAMETER;
  }

  *Control = EFI_SERIAL_OUTPUT_BUFFER_EMPTY;
  if (SerialPortPoll ()) {
    *Control |= EFI_SERIAL_INPUT_BUFFER_EMPTY;
  }
  return RETURN_SUCCESS;
}

/**
  Сброс приёмного/передающего тракта.
**/
RETURN_STATUS
EFIAPI
SerialPortFlush (
  VOID
  )
{
  UINTN  Base = UartBase ();

  MmioWrite32 (Base + UARTDM_CR, UARTDM_CR_RST_RX | UARTDM_CR_RST_TX);
  return RETURN_SUCCESS;
}
