#!/bin/bash
# platform.sh.inc для MSM8937/8940 (ugg) — переопределяет сборку boot.img
# из Silicon/platform.sh.inc.
#
# Что важно для этого устройства (проверено на телефоне):
#   1) LK ждёт не одиночный .dtb, а ВЕСЬ хвост стокового kernel: два DTB подряд
#      (~627 КБ). Он лежит в repo как Platform/Xiaomi/msm8937/FdtBlob_compat/ugg.dtblock.
#      Без него LK отвечает "dtb not found" и образ не запускается.
#   2) Адреса как в стоковом boot.img: base 0x80000000, kernel 0x80008000,
#      ramdisk 0x81000000, tags 0x80000100.
#   3) kernel = BootShim.bin + gzip(UEFI FD) + DT-блок; BootShim копирует FD
#      в FD_BASE (0x8EA00000) и прыгает туда.
#
# SPDX-License-Identifier: BSD-2-Clause-Patent

function platform_build_kernel(){
	local FV_DIR="${WORKSPACE}/Build/${DEVICE}/${_MODE}_${TOOLCHAIN}/FV"
	local FD="${FV_DIR}/${SOC_PLATFORM}_UEFI.fd"
	local OUT="${WORKSPACE}/uefi-${DEVICE}-kernel"
	local COMPAT="${ROOTDIR}/Platform/${VENDOR_NAME}/${SOC_PLATFORM_L}/FdtBlob_compat"

	[ -f "${FD}" ] || { echo "platform.sh.inc: нет ${FD}" >&2; return 1; }

	cat "${ROOTDIR}/tools/BootShim/BootShim.bin" "${FD}" \
		| gzip -9 -c > "${WORKSPACE}/uefi-${DEVICE}.img.gz" || return 1

	cat "${WORKSPACE}/uefi-${DEVICE}.img.gz" > "${OUT}" || return 1

	local DTBLOCK="${COMPAT}/${PLATFORM_NAME}.dtblock"
	[ -f "${DTBLOCK}" ] || DTBLOCK="${COMPAT}/${PLATFORM_NAME}.dtb"

	if [ -f "${DTBLOCK}" ]; then
		echo "platform.sh.inc: DT-блок $(basename "${DTBLOCK}") ($(stat -c%s "${DTBLOCK}") байт)"
		cat "${DTBLOCK}" >> "${OUT}" || return 1
	else
		echo "platform.sh.inc: нет DT-блока в ${COMPAT} -> LK ответит 'dtb not found'" >&2
		return 1
	fi
}

function platform_build_bootimg(){
	python3 "${ROOTDIR}/tools/mkbootimg.py" \
		--kernel "${WORKSPACE}/uefi-${DEVICE}-kernel" \
		--ramdisk "${ROOTDIR}/ramdisk" \
		--base 0x80000000 \
		--kernel_offset 0x00008000 \
		--ramdisk_offset 0x01000000 \
		--tags_offset 0x00000100 \
		--header_version 0 \
		-o "${OUTDIR}/boot-${DEVICE}${EXT}.img" \
		|| return "$?"
}
