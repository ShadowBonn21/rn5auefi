#!/bin/bash
# platform.sh.inc для MSM8937/8940 — переопределяет сборку boot.img из
# Silicon/platform.sh.inc, потому что у нас НЕТ готового FdtBlob_compat/<device>.dtb.
#
# Логика та же, что в edk2-msm:
#   kernel = BootShim.bin + gzip(FD) [+ dtb]
#   boot.img = mkbootimg(v0)
#
# DTB подхватывается автоматически, если он лежит в
#   Platform/Xiaomi/msm8937/FdtBlob_compat/${PLATFORM_NAME}.dtb
# (собрать из msm8937 dtsi — см. docs/05-build.md).
#
# SPDX-License-Identifier: BSD-2-Clause-Patent

function platform_build_kernel(){
	local FV_DIR="${WORKSPACE}/Build/${DEVICE}/${_MODE}_${TOOLCHAIN}/FV"
	local FD="${FV_DIR}/${SOC_PLATFORM}_UEFI.fd"
	local OUT="${WORKSPACE}/uefi-${DEVICE}-kernel"

	[ -f "${FD}" ] || { echo "нет ${FD}" >&2; return 1; }

	cat "${ROOTDIR}/tools/BootShim/BootShim.bin" "${FD}" \
		| gzip -9 -c > "${WORKSPACE}/uefi-${DEVICE}.img.gz" || return 1

	cat "${WORKSPACE}/uefi-${DEVICE}.img.gz" > "${OUT}" || return 1

	local DTB="${ROOTDIR}/Platform/${VENDOR_NAME}/${SOC_PLATFORM_L}/FdtBlob_compat/${PLATFORM_NAME}.dtb"
	if [ -f "${DTB}" ]; then
		echo "kernel: добавляю ${DTB}"
		cat "${DTB}" >> "${OUT}" || return 1
	else
		echo "kernel: DTB не найден, собираю без него (LK передаст свой)"
	fi
}

function platform_build_bootimg(){
	python3 "${ROOTDIR}/tools/mkbootimg.py" \
		--kernel "${WORKSPACE}/uefi-${DEVICE}-kernel" \
		--ramdisk "${ROOTDIR}/ramdisk" \
		--kernel_offset 0x00008000 \
		--ramdisk_offset 0x01000000 \
		--tags_offset 0x00000100 \
		--header_version 0 \
		-o "${OUTDIR}/boot-${DEVICE}${EXT}.img" \
		|| return "$?"
}
