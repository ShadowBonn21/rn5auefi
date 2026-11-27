/** @file
  UggTestApp — проверка того, что UEFI умеет загружать и запускать
  приложение из FV (это тот же путь, которым запускаются GRUB/LinuxLoader).

  Приложение ничего не делает с оборудованием: печатает текст через
  ConOut (наша реализация SimpleTextOut в UggFbDxe) и возвращает успех.
  Если строки на экране появились — цепочка «BDS -> LoadImage -> StartImage»
  работает, и дальше на её место можно ставить загрузчик Linux.

  Copyright (c) 2026, UGG UEFI project. SPDX-License-Identifier: BSD-2-Clause-Patent
**/

#include <Uefi.h>
#include <Library/UefiApplicationEntryPoint.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>

/**
  Точка входа приложения.

  @param[in] ImageHandle  Хэндл образа.
  @param[in] SystemTable  Таблица системных сервисов.

  @retval EFI_SUCCESS  Всегда.
**/
EFI_STATUS
EFIAPI
UefiMain (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  if (gST->ConOut != NULL) {
    gST->ConOut->OutputString (gST->ConOut, L"\r\n");
    gST->ConOut->OutputString (gST->ConOut, L"=== UGG TEST APP RUNNING ===\r\n");
    gST->ConOut->OutputString (gST->ConOut, L"UEFI can load and start images\r\n");
    gST->ConOut->OutputString (gST->ConOut, L"this is the path for GRUB/LinuxLoader\r\n");
    gST->ConOut->OutputString (gST->ConOut, L"============================\r\n");
  }

  /* Подождём немного, чтобы текст успели прочитать (10 x 100 мс). */
  gBS->Stall (1000000);

  return EFI_SUCCESS;
}
