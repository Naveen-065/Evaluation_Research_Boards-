CROSS_COMPILE ?= aarch64-linux-gnu-
CC := $(CROSS_COMPILE)gcc
HOST_CC ?= cc
PYTHON ?= python3

BUILD_DIR := build
TARGET := $(BUILD_DIR)/zes-edac-relay
STUB_TARGET := $(BUILD_DIR)/zes-edac-relay-stub
VENDOR_DIR := vendor/zes
VENDOR_LIB := $(VENDOR_DIR)/zesEDAC_LN_AA64_NV_v1.3.0_b01_release.a

CPPFLAGS := -Iinclude -I$(VENDOR_DIR)
CFLAGS := -std=c11 -O2 -g -Wall -Wextra -Wpedantic -Werror
LDFLAGS := -static
LDLIBS :=

.PHONY: all clean native-stub test-native verify-vendor

all: $(TARGET)

$(BUILD_DIR):
	mkdir -p $@

$(TARGET): src/zes_relay.c include/zes_protocol.h $(VENDOR_LIB) | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ src/zes_relay.c $(VENDOR_LIB) $(LDLIBS)

native-stub: $(STUB_TARGET)

$(STUB_TARGET): src/zes_relay.c tests/zes_stub.c include/zes_protocol.h $(VENDOR_DIR)/zesEdacV130.h | $(BUILD_DIR)
	$(HOST_CC) $(CPPFLAGS) $(CFLAGS) -o $@ src/zes_relay.c tests/zes_stub.c

test-native: $(STUB_TARGET)
	$(PYTHON) tests/test_relay_protocol.py $(STUB_TARGET)

verify-vendor:
	@printf '%s  %s\n' 'b8192785cd3466dc491b1eeaf8da8be98bc4fe0a40ff6688d248d3a675be03b4' '$(VENDOR_LIB)' | sha256sum -c -
	@printf '%s  %s\n' '1c14e54c4a0545350b28aede434cadbf9076be2e019cc0f5d4ccf554b4129375' '$(VENDOR_DIR)/zesEdacV130.h' | sha256sum -c -

clean:
	rm -f $(TARGET) $(STUB_TARGET)
