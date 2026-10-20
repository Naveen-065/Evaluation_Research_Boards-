"""Enumerate D2XX devices without opening or changing any GPIO."""
import ctypes as C
import json

def devices():
    dll = C.WinDLL('ftd2xx.dll')
    count = C.c_ulong()
    status = dll.FT_CreateDeviceInfoList(C.byref(count))
    if status:
        raise RuntimeError(f'FT_CreateDeviceInfoList status={status}')
    result = []
    for index in range(count.value):
        flags, kind, usb_id, location = (C.c_ulong() for _ in range(4))
        serial, description = C.create_string_buffer(16), C.create_string_buffer(64)
        handle = C.c_void_p()
        status = dll.FT_GetDeviceInfoDetail(index, C.byref(flags), C.byref(kind),
            C.byref(usb_id), C.byref(location), serial, description, C.byref(handle))
        if status:
            raise RuntimeError(f'FT_GetDeviceInfoDetail index={index} status={status}')
        result.append(dict(index=index, flags=flags.value, kind=kind.value,
            usb_id=f'{usb_id.value:08x}', location=location.value,
            serial=serial.value.decode(), description=description.value.decode()))
    return result

if __name__ == '__main__':
    print(json.dumps(devices(), indent=2))
