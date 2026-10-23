#include <stdint.h>
#include <string.h>

#include "zesEdacV130.h"

#define DATA_WORDS 256
#define PARITY_WORDS 18
#define DATA_BITS 8192u

static void signature(const int *data, uint32_t *syndrome, uint32_t *overall)
{
    const uint32_t *words = (const uint32_t *)data;
    uint32_t position_xor = 0u;
    uint32_t bit_xor = 0u;

    for (uint32_t word = 0; word < DATA_WORDS; word++) {
        uint32_t value = words[word];
        for (uint32_t bit = 0; bit < 32u; bit++) {
            if (((value >> bit) & 1u) != 0u) {
                position_xor ^= word * 32u + bit + 1u;
                bit_xor ^= 1u;
            }
        }
    }
    *syndrome = position_xor;
    *overall = bit_xor;
}

void encodeAllRowColPariBits(int *datablock, int *pariRowCol)
{
    uint32_t syndrome;
    uint32_t overall;

    memset(pariRowCol, 0, PARITY_WORDS * sizeof(int));
    signature(datablock, &syndrome, &overall);
    pariRowCol[0] = (int)syndrome;
    pariRowCol[1] = (int)overall;
}

int decodeAndCorrectData(int *errW, int *prevPariRowCol, int threshold)
{
    uint32_t syndrome;
    uint32_t overall;
    uint32_t error_position;
    uint32_t expected_syndrome = (uint32_t)prevPariRowCol[0];
    uint32_t expected_overall = (uint32_t)prevPariRowCol[1];

    (void)threshold;
    signature(errW, &syndrome, &overall);
    if (syndrome == expected_syndrome && overall == expected_overall) {
        return 0;
    }
    error_position = syndrome ^ expected_syndrome;
    if ((overall ^ expected_overall) == 1u &&
        error_position >= 1u && error_position <= DATA_BITS) {
        uint32_t zero_based = error_position - 1u;
        ((uint32_t *)errW)[zero_based / 32u] ^= 1u << (zero_based % 32u);
        signature(errW, &syndrome, &overall);
        if (syndrome == expected_syndrome && overall == expected_overall) {
            return 1;
        }
    }
    return 2;
}

int intDataBufferSize(void)
{
    return DATA_WORDS;
}

int intParityBufferSize(void)
{
    return PARITY_WORDS;
}

float compressionRatio(void)
{
    return 72.0f / 1024.0f;
}

const char *getVersion(void)
{
    return "protocol-test-stub-1";
}
