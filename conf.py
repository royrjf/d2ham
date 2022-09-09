#!/usr/bin/python3

gravity_doc = """
protocol:
    MASTER -> ADDR_1byte CMD_1byte DATA CRC_32bit

        D -> push a magnet, follow 1byte channel, and 1byte timeout 5ms unit

    SLAVE  -> ADDR o k CRC_32bit
    SLAVE  -> ADDR e r r CRC_32bit
        
"""

spring_doc = """
protocol:
    MASTER -> FA FE addr num round command DA EF
        ex: b'\xfa\xfe\x01\x0a\x01\xff\xda\xef'

    SLAVE -> 

"""

drop_doc = """
recv only now,
    got b'\xff\x0c\xb0\x07\x00\x00\x08\xa0\xff\xaf\xfe'  -> OPEN
    else -> BLOCK
"""

ac_doc = """
protocol:
    MASTER -> 5A 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 D2

    SLAVE -> 5A 01 01 F3 00 00 76 02 00 00 00 02 00 00 32 00 00 AA
"""

DEV_LIST = [
    {'name': 'Y', 'dev_name': '/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DO02G7QA-if00-port0','type': 'RS485', 'baud': 115200,'timeout': 3, 'DOC': ac_doc},  #usb-FTDI_FT230X_Basic_UART_DO01N0B9-if00-port0  DO02GNWH
    {'name': 'GRAVITY', 'dev_name': '/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DK0B1FIK-if00-port0', 'type':'RS485', 'baud':115200, 'timeout':0.2, 'DOC':gravity_doc},
    {'name': 'SPRIN', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D1_b0001-if01-port0', 'type':'RS485', 'baud':9600, 'timeout': 10, 'DOC':spring_doc},
    {'name': 'DROP', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D1_b0001-if02-port0', 'type':'RS485', 'baud':9600, 'timeout': 0.5, 'DOC':drop_doc},
    {'name': 'AC', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D1_b0001-if03-port0', 'type': 'TTL232', 'baud': 9600, 'timeout': 0.5, 'DOC': ac_doc},
    {'name': 'DROP1', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D2_b0001-if00-port0', 'type':'RS485', 'baud':9600, 'timeout':0.5, 'DOC':gravity_doc},
    {'name': 'DROP2', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D2_b0001-if01-port0', 'type':'RS485', 'baud':9600, 'timeout': 0.5, 'DOC':spring_doc},
    {'name': 'AC1', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D2_b0001-if02-port0', 'type':'RS485', 'baud':9600, 'timeout': 0.5, 'DOC':drop_doc},
    {'name': 'AC2', 'dev_name': '/dev/serial/by-id/usb-fusionRobotics_D2_b0001-if03-port0', 'type': 'RS485', 'baud': 9600, 'timeout': 0.5, 'DOC': ac_doc}
]
