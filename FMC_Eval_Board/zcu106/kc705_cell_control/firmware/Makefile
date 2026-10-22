# Build separately; never overwrite the deployed gui_wb_mode.bin.
TOOLCHAIN_PREFIX ?= riscv64-unknown-elf
ARCH ?= rv32i_zicsr
SDK := sdk
OUT := rebuilt
SOURCES := $(SDK)/crt0_vex.S $(SDK)/isr.c $(SDK)/stub.c gui_wb_mode.c

.PHONY: all
all: $(OUT)/gui_wb_mode.bin $(OUT)/gui_wb_mode.hex

$(OUT):
	mkdir -p $@

$(OUT)/gui_wb_mode.elf: $(SOURCES) $(SDK)/sections.lds $(wildcard $(SDK)/*.h $(SDK)/generated/*.h $(SDK)/hw/*.h) | $(OUT)
	$(TOOLCHAIN_PREFIX)-gcc -I$(SDK) -I$(SDK)/generated -O0 \
		-mabi=ilp32 -march=$(ARCH) -D__vexriscv__ \
		-Wl,-Bstatic,-T,$(SDK)/sections.lds,--strip-debug -ffreestanding -nostdlib \
		-o $@ $(SOURCES)

$(OUT)/gui_wb_mode.bin: $(OUT)/gui_wb_mode.elf
	$(TOOLCHAIN_PREFIX)-objcopy -O binary $< $@

$(OUT)/gui_wb_mode.hex: $(OUT)/gui_wb_mode.elf
	$(TOOLCHAIN_PREFIX)-objcopy -O verilog $< $@
	sed -i 's/@1000/@0000/g' $@
