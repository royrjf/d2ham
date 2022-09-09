#!/usr/bin/python3

import serial
import time
import os

def _search_device():
    try:
        rev = os.listdir('/dev/serial/by-id/')
    except Exception as ex:
        print('no serial port found?!')
        return ''
    
    for d in rev:
        if d.find('1a86') >0:
            rev = '/dev/serial/by-id/' + d
            print('found hub device: %s' %rev)
            return rev
    return ''      
def _connect():
    ptime=time.time()
    while 1:
        dev=_search_device()
        if dev=='':
            print('6')
        else:
            break
        time.sleep(0.05)
        ntime=time.time()    
        delta=ntime-ptime
        if delta>1:
            return False
    retry=5
    for i in range(retry):
        try:
            print('dev->%s'%dev)
            ser=serial.Serial('/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0',115200,timeout=0.5)
            print('link success')
            return ser
        except Exception as ex:
            print('exception: %s' %ex)
    return False
def Hi():
    ser=_connect()
    if ser==False:
        return False
    else:
        retry=2
        for i in range(retry):
            try:
                ser.write(b'\x53\x01\x00\x00\x00\x54')
                rev=ser.read(6)
                if rev==b'hello':
                    ser.flush()
                    ser.flushInput()
                    ser.flushOutput()
                    ser.close()
                    return True
                else:
                    try:
                        ser.flush()
                        ser.flushInput()
                        ser.flushOutput()
                        ser.close()
                    except:
                        pass
                    print('%s'%rev)
                    return False
            except:
                return False
def RstSerial(serial_id):
    CMD_BIT=1
    cmd=[0x53,0x02,serial_id,0]
    cmd[3]=0x53+0x02+serial_id
    command=list2bytes(cmd)
    ser=_connect()
    if ser==False:
        print('1')
        return False
    retry=2
    for i in range(retry):
        try:
            ser.write(command)
            rev=ser.read(6)
            #print('rev-->%s'%rev)
            ser.flush()
            ser.flushInput()
            ser.flushOutput()
            ser.close()
            if rev==command:
                return True
        except:  
            ser.close()  
            pass
    return False
def rstPc():
    cmd=[0x53,0x04,0x57]
    command=list2bytes(cmd)
    ser=_connect()
    if ser==False:
        print('1')
        return False
    retry=2
    for i in range(retry):
        try:
            ser.write(command)
            #rev=ser.read(6)
            #print('rev-->%s'%rev)
            ser.flush()
            ser.flushInput()
            ser.flushOutput()
            ser.close()
            if rev==command:
                return True
        except:  
            ser.close()  
            pass
    return False
def list2bytes(cmd_list):
    cmd=''
    l_list=list(map(chr,cmd_list))
    for d in l_list:
        cmd+=d
    cmd=cmd.encode('latin-1')
    return cmd
    
    
    
