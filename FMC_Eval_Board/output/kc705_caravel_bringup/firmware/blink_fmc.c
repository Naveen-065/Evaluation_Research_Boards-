#include <defs.h>
#include <stub.h>

/* Dedicated management GPIO drives daughtercard D5. Leave the user GPIO
 * configuration and housekeeping SPI pins at their power-on defaults. */
static void delay_ticks(unsigned int ticks)
{
    reg_timer0_config = 0;
    reg_timer0_data = ticks;
    reg_timer0_config = 1;
    reg_timer0_update = 1;
    while (reg_timer0_value > 0) reg_timer0_update = 1;
}

void main(void)
{
    reg_gpio_mode1 = 1;
    reg_gpio_mode0 = 0;
    reg_gpio_ien = 1;
    reg_gpio_oe = 1;
    while (1) {
        reg_gpio_out = 0;
        delay_ticks(5000000); /* 0.5 s at a 10 MHz management CPU clock. */
        reg_gpio_out = 1;
        delay_ticks(5000000);
    }
}
