#!/usr/bin/python3

import sys
import os
import time
import socket
import threading
import traceback
from rcomm import Rcomm
from serv import Serv
from queue import LifoQueue
from crc import custom_crc32
from checkcom import Checkusb
import crcmod.predefined
from YModem import YModem
import platform
from binascii import a2b_hex
from utils import bstr2int
import copy
import crcmod
import struct
import logging
import logging.handlers
import json
import rstserial
import random
curDir = os.path.abspath(os.path.dirname(__file__))
logPath = os.path.join(curDir, "log", "ham.log")
#binPath = os.path.join(curDir, "d.bin")
trace = logging.getLogger()
trace.setLevel(logging.DEBUG)
formatter = logging.Formatter(fmt="%(asctime)s %(filename)s[line:%(lineno)d]%(levelname)s - %(message)s",
                                  datefmt="%m/%d/%Y %I:%M:%S %p")
#file_handler = logging.FileHandler("daemon.log")
#file_handler = logging.handlers.TimedRotatingFileHandler("/home/ruijunfeng/works/fusion/d2ham/log/daemon.log", when='d', interval=1, backupCount=90)
file_handler = logging.handlers.TimedRotatingFileHandler(logPath, when='d', interval=1, backupCount=15)
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setFormatter(formatter)  # 可以通过setFormatter指定输出格式
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
console.setFormatter(formatter)
trace.addHandler(console)
trace.addHandler(file_handler)
trace.info('hello')
trace.info('%s'%logPath)
__VERSION__ = '0.1'
#2019.11.27 midware support multi machine
#2019.12.30 midware support d1
#2019.12.30 rcomm process_rx add open dv 3 times
#2020.3.5 multimachine online
#2020.3.26 support 3 device
#2020.4.28 Y2C convey belt
#2020.5.11 modify cmd cabinet and add machine
#2020.5.57 v3.1 drop_test
#2020.6.17 V3.1.1 pcb_update
#2020.7.28 v3.2 record_drop
#2020.8.4 V3.2.1 remove gravity retry
#2020.9.9 v4.0 record drop
#2020.12.10 v4.2 protol add id
#2021.01.13 v4.2.2 drop_poll ac_poll bug
#2021.03.19 v4.2.3 change log Storage 90 day to 10 day
#2021.03.30 V4.24 d2.json bug
#2021.12.10 v5.0 M3 bailu y
#2021 12.23 v5.1 Y2 Exchange_Drv address x,y
#2022 1.24 m3 ws2813 led control  Y reset hub
class Daemon( threading.Thread ):
    EX_FLAG = {'EX_NORM':0x00, 'EX_OPEN':0x01, 'EX_CLOSE':0x02, 'EX_CLOSE_FORCE':0x04}
    sensor_bm = ('GEAR', 'DOOR', 'ADC_SOA', 'ADC_SOB', 'ADC_SOC')
    def __init__(self):
        super(Daemon, self).__init__()
        self._stop_event = threading.Event()
        self.led_state=[]
        self.drop_state=['','','']
        self.usb_state=1
        self.cabinet_count=1
        self.addr='x'
        self.res_cache = {} # format: {"id": {"res": {}, "time": 1234}, "id2":...}
        self.res_cache_timeout = 5
        self.drop=['DROP','DROP1','DROP2']
        self.ac=['AC','AC1','AC2']
        self.ac_last_t=[20,20,20]
        self.ac_last_h=[60,60,60]
        self.Y_MODE=""
        self.spring_start_time=0
        self.spring_stop_time=0
        self.spring_dict={}
        pcname=platform.node()
        if pcname=="37101":#huaqiao
            self.Y_MODE="huaqiao"
        if pcname=="37111":#kunshan bailu
            self.Y_MODE="bailu"
        if pcname.find('D4')==0:
            self.D_MODE="D4"
        if pcname.find('D3')==0:
            self.D_MODE="D3"
        if pcname.find('rui')==0:
            self.D_MODE="D2"
        if pcname.find('D2')==0:
            self.D_MODE="D2"
        if pcname.find('D1')==0:
            self.D_MODE="D1"
        self.crc_func = crcmod.mkCrcFun(0x11021, rev=False, initCrc=0x0000, xorOut=0x0000)

    def join(self, timeout=1):
        self._stop_event.set()
        self.rcomm.join()
        self.serv.join()
        self.checkcom.join()
        self._stop_event.set()
        super(Daemon, self).join(timeout)
    
    def run(self):
        pcname=platform.node()
        if pcname.find('D'):
            pass
        else:
            self.process_usb_init()
        self.init_rcomm()
        self.init_serv()
        self.init_checkusb()
        while not self._stop_event.is_set():
            time.sleep(0.5)
    def init_checkusb(self):
        self.checkusb = Checkusb(trace)
        self.checkusb.start()
    def init_rcomm(self):
        self.rcomm = Rcomm(trace)
        self.rcomm.start()
    
    def init_serv(self):
        self.serv = Serv(trace, gui_port=7651)
        self.serv.process_gui_hook = self._process_gui_hook
        self.serv.start()
    
    def _process_gui_hook(self, gui_sock):
        try:
            data = gui_sock.recv_json()
            trace.info('gui msg: %s' %(data))
            self.process_gui_json(gui_sock, data)
        except Exception as ex:
            #trace.error(traceback.format_exc(sys.exc_info()[-1]))
            trace.error('failed to process json: %s' % (ex))
            gui_sock.send_json({})
            return False
    def process_gui_json(self, gui_sock, data):
        req = data.get('req', False)
        if req is False:
            gui_sock.send_json({})
            return
        device = req.get('device', False)
        if device is False:
            trace.warning('failed to get device')
            gui_sock.send_json({})
            return
        rev = getattr(self, 'process_device_%s' % (device))(req)
        trace.debug('send_json -> %s' % str(rev))
        gui_sock.send_json(rev)
    def process_device_m3(self, data):
        cmd = data.get('command', False)
        if cmd is False:
            return {}
        if cmd=='hi':
            rev={'rep': {'device':'m3', 'result':'hi'}}
            return 
        elif cmd=='ac_poll':
            t=random.uniform(9,10)
            h=40.3
            return {'rep': {'device':'m3', 'result':'sussess','t':t,'h':h}}
        elif cmd=='hi_pcb':
            board=data.get('board',False)
            if board==False:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            if board =='lattice':
                command='lH'
            if board == 'beans':
                command='OH'
            command = command.encode('latin-1')
            crc = struct.pack('H', self.crc_func(command))
            command+= crc    
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='pcb_version':
            rev=self.m3_pcb_version(data)
            if rev==False:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            else:
                return {'rep': {'device': 'm3', 'result': rev}}
        elif cmd=="lattice_led_control":
            rev=self.m3_lattice_led_control(data)
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}                
        elif cmd =="xl9535_set":
            para_list=data.get('para')
            board=data.get('board')
            if board=='lattice':
                board_addr='l'
            if board=='beans':
                board_addr='O'
            xl9535_addr=chr(int(data.get('xl9535_addr')))
            rev=self.m3_gen_frame(board_addr,'X',xl9535_addr,'%c%c%c'%(para_list[0],para_list[1],para_list[2]))
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd =='xl9535_read':
            board=data.get('board')
            if board=='lattice':
                board_addr='l'
            if board=='beans':
                board_addr='O'
            rev=self.m3_gen_frame(board_addr,'Y',chr(1),'')
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd =="lattice_sensor":
            devAddr=data.get('devAddr')
            rev=self.m3_lattice_gen_frame(devAddr,'i','')
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=="lattice_lock_driver":
            lock_ids=self.m3_lattile_lock_driver_process(data)
            rev=self.m3_lattice_gen_frame('d',lock_ids)
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=="lattice_led_clear":
            rev=self.m3_lattice_led_clear()
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=="lattice_close_all_led":
            rev=self.m3_lattice_close_all_led()
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=='lucky_key':
            command='Os'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big') 
            command=command.encode()
            command+=crc
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'Os'):
                    return {'rep': {'device': 'm3', 'result': 'success','sensor':chr(r[2])}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'd', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='led_colour':
            rev=self.m3_open_rgb_led(data)
            if rev==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='open_led':
            colour=data.get('colour',False)
            command='AM%c'%colour
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            return {'rep': {'device': 'y', 'result': 'success'}}
        elif cmd=='close_leds':
            command='An'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            return {'rep': {'device': 'y', 'result': 'success'}}
        elif cmd=='led_colour_test':
            led_id=data.get('led_id',False)
            if led_id==False:
                return {'rep': {'device':'m3', 'result':'error'}}
            led_id=int(led_id)
           
            rgb=data.get('colour',False)
            
            rgb=int(rgb)
            s = '%s%s' % (chr(rgb),chr(int(led_id)))
            command='AN'+s
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='led_colour_normal':
            led_id=data.get('led_id',False)
            if led_id==False:
                return {'rep': {'device':'m3', 'result':'error'}}
            led_id=int(led_id)
            if led_id//100==1:
                led_id=led_id%100+26
            elif led_id//100==2:
                led_id=led_id%100+13
            elif led_id//100==3:
                led_id=led_id%100
            else:
                return {'rep': {'device':'m3', 'result':'error'}}
            rgb=data.get('colour',False)
            rgb=int(rgb)
            s = '%s%s' % (chr(rgb),chr(led_id))
            command='AN'+s
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='lid_control':
            rev=self.m3_lid_control_process(data)
            if rev==True:
                return {'rep': {'device': 'm3', 'result': 'success'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=='lid_poll':  
            rev=self.m3_lid_poll_process(data)
            if rev==False:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            else:
                return {'rep': {'device': 'm3', 'result': 'success','mate':rev}}
        elif cmd=='drop_beans':
            ch=data.get('ch',False)
            if ch==False:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            circle=data.get('circle',False)
            if circle==False:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            command=''
            if int(ch)>7 or int(ch)<1:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            if int(circle)>20:
                return {'rep': {'device': 'm3', 'result': 'error'}}
            command='OD%c%c%c'%(1,int(ch),int(circle))
            trace.info('command-->%s'%command)  
            command = command.encode('latin-1')
            crc = struct.pack('H', self.crc_func(command))
            command+= crc
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=1.5*int(circle))
                if r.startswith(b'OMOK'):
                    return {'rep': {'device': 'm3', 'result': 'success'}}
                elif r.startswith(b'OMERR'):
                    return {'rep': {'device': 'm3', 'result': 'error'}}
                else:
                    return {'rep': {'device': 'm3', 'result': 'error'}}
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='drop_stop':
            command='AN'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big') 
            command=command.encode()
            command+=crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='open_door':
            command=b'kP1\x03\x1f\xc4'
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'kP'):
                    return {'rep': {'device': 'm3', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='close_door':
            command=b'kP1\x03\x1f\xc4'
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'kP'):
                    return {'rep': {'device': 'm3', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='drop_cup':
            rev=self.m3_drop_cup(data)
            if rev==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            elif rev==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error','meta':rev}}
        elif cmd=='lock_sensor':
            sensor_id=data.get('sensor_id',False)
            if sensor_id==False:
                return {'rep': {'device':'d', 'result':'error'}}
            command='Es%c'%int(sensor_id)
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command=command.encode('latin-1')
            command=command+crc
            trace.info('cmd-->%s'%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'Es'):
                    return {'rep': {'device': 'm3', 'result': 'success','sensor':chr(r[2])}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
            return {'rep': {'device': 'm3', 'result': 'success'}}
        elif cmd=='lock_test_new':
            command='EM'
            lock_id=data.get('lock_id',False)
            if lock_id==False:
                return {'rep': {'device':'d', 'result':'error'}}
            try:
                lock_id = list(map(int, lock_id.split(',')))
            except Exception as ex:
                trace.error('lock id invalid: %s' %ex)
                return {'rep': {'device':'d', 'result':'error'}}
            for num in lock_id:
                if num//100==1:
                    num=num%100+32
                    if num>=37:
                        num=num+1
                elif num//100==2:
                    num=num%100+16
                elif num//100==3:
                    num=num%100
                else:
                    return {'rep': {'device':'m3', 'result':'error'}}
                s = '%s' % (chr(num))
                if num==36:
                    command+='$%'
                else:
                    command+=s
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command=command.encode('latin-1')
            command=command+crc
            trace.info('cmd%s'%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                return {'rep': {'device': 'm3', 'result': 'success'}}
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=='lock_test':
            lock_id=data.get('lock_id',False)
            if lock_id==False:
                return {'rep': {'device':'m3', 'result':'error'}}
            command='EM%c'%int(lock_id)
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command=command.encode('latin-1')
            command=command+crc
            trace.info('cmd-->%s'%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                return {'rep': {'device': 'm3', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=='lock':
            retry=3
            for i in range(0,retry):
                rev= self.m3_process_open_lock(data)
                if rev== True:
                    return {'rep': {'device': 'm3', 'result': 'success'}}
            return {'rep': {'device': 'm3', 'result': 'error'}}
        elif cmd=='switch':
            return {'rep': {'device': 'm3', 'result': 'success'}}
    def process_device_y(self, data):
        cmd = data.get('command', False)
        if cmd is False:
            return {}
        if cmd=='hi':
            return {'rep': {'device':'y', 'result':'hi'}}
        if cmd=='hi_pcb':
            command='AH'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s' %command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            return {'rep': {'device': 'y', 'result': 'success'}}
        elif cmd=='idle':
            if self.idle()==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='exdoor_is_closed':
            rev=''
            rev=self.ex_is_closed()
            return {'rep': {'device':'y', 'result':rev}}
        elif cmd=='home':
            rev=''
            rev=self.home(300)
            if rev==True:
                return {'rep': {'device':'y', 'result':'success'}}
            else:
                return {'rep': {'device':'y', 'result':'error'}}
        elif cmd=='led':
            rgb_list=data.get('rgb')
            trace.info('%s'%rgb_list)
            if self.led(rgb_list)==True:
                return {'rep': {'device':'y', 'result':'success'}}
            else:
                return {'rep': {'device':'y', 'result':'error'}}
        elif cmd=='exdoor_is_opened':
            rev=self.ex_is_opened()
            return {'rep': {'device':'y', 'result':rev}}
        elif cmd=='sensor_door':
            block=''
            rev=self.sensor(board='door_board')
            block=rev.get('DOOR')
            return {'rep': {'device':'y', 'result': "success", 'block':block}}
        elif cmd=='sensor_ex':
            block=''
            rev=self.sensor(board='ex_board')
            block=rev.get('DOOR')
            return {'rep': {'device':'y', 'result': "success", 'block':block}}
        elif cmd=='qd_read':
            rev=self.qd_read()
            return {'rep': {'device':'y', 'result':rev}}
        elif cmd=='ex_open':
            self.led([101,101,101]*10)
            if self.ex_open()==True:
                return {'rep': {'device':'y', 'result':'success'}}
            else:
                return {'rep': {'device':'y', 'result':'error'}}
        elif cmd=='ex_close':
            self.led([0,0,0]*10)
            dc=data.get('door_check',False)
            if self.ex_close()==True:
                return {'rep': {'device':'y', 'result':'success'}}
            else:
                return {'rep': {'device':'y', 'result':'error'}}
        elif cmd=='version':
            return {'rep': {'device':'y', 'result':'y version 3.1 2020/06/8 Y2C cmd convey_belt_on'}}
        elif cmd=='read_pwr':
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            command ='%s,READ_BELT_POWER,' %chr(ord('A')+int(cabinet)-1)   
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+=crc
            trace.info('command-->%s'%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            except:
                return {'rep': {'device': 'y', 'result': 'error'}}
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='convey_belt_brake':
            command='UY'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+=crc
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            except:
                return {'rep': {'device': 'y', 'result': 'error'}}
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r==b'%cYOK\r\n'%cmd_list[i][0].encode():  
                    return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='extenal_belt_bailu':
            #bailu
            state='success'
            PSC=99
            belt_id=data.get('belt_ids',False)
            if belt_id==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            belt_id_list=[int(i) for i in belt_id.split(',')]
            
            speed=data.get('speed',False)
            if speed==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            speed_list=[int(i) for i in speed.split(',')]
            
            for i in range(0,len(speed_list)):
                if speed_list[i]==0:
                    speed_list[i]=0
                elif speed_list[i]==1:
                    speed_list[i]=35
                elif speed_list[i]==2:
                    speed_list[i]=45
                elif speed_list[i]==3:
                    speed_list[i]=55
                elif speed_list[i]==4:
                    speed_list[i]=65
                elif speed_list[i]==5:
                    speed_list[i]=75
                elif speed_list[i]==6:
                    speed_list[i]=85
                else:
                    speed_list[i]=50
            direction=data.get('direction',False)
            if direction==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction_list=direction.split(',')
      
            if (len(belt_id_list)!=len(belt_id_list)) or (len(belt_id_list)!=len(belt_id_list)) or (len(belt_id_list)!=len(belt_id_list)):
                trace.info("recv info format error")
                return {'rep': {'device': 'y', 'result': 'error'}}
                
            cmd_list=['aXc','bXc','cXc']
            for i in range(0,len(belt_id_list)):
                if belt_id_list[i]>=1 and belt_id_list[i]<=4:
                    cmd_list[0]+=str(belt_id_list[i])
                    cmd_list[0]+=chr(speed_list[i])
                    cmd_list[0]+=direction_list[i]
                elif belt_id_list[i]>=5 and belt_id_list[i]<=8:
                    cmd_list[1]+=str(belt_id_list[i]-4)
                    cmd_list[1]+=chr(speed_list[i])
                    cmd_list[1]+=direction_list[i]
                elif belt_id_list[i]>=9 and belt_id_list[i]<=12:
                    cmd_list[2]+=str(belt_id_list[i]-8)
                    cmd_list[2]+=chr(speed_list[i])
                    cmd_list[2]+=direction_list[i]
                else:
                    trace.info('more than 12 belt are not support')
                    return {'rep': {'device': 'y', 'result': 'error'}}
            for i in range(0,(len(cmd_list))):
                if len(cmd_list[i]) >3:
                    command=cmd_list[i]
                    crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                    command = command.encode('latin-1')
                    command+= crc
                    retry=2
                    trace.info('%s'%command)
                    for j in range(0,retry):
                        try:
                            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                        except:
                            trace.error('send error')
                            state='error'
                        try:
                            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                            if r==b'%cXOK\r\n'%cmd_list[i][0].encode():   
                                break
                            else:
                                trace.error('ack-->%s' %r)
                                pass
                        except:
                            state='error'
                            trace.error('no ack')
            return {'rep': {'device': 'y', 'result': state}}       
        elif cmd=='extenal_belt':
            cmd_id_list=[]
            state='success'
            PSC=99
            belt_id=data.get('belt_ids',False)
            if belt_id==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            belt_id_list=[int(i) for i in belt_id.split(',')]
            speed=data.get('speed',False)
            if speed==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            speed_list=[int(i) for i in speed.split(',')]
            
            for i in range(0,len(speed_list)):
                if speed_list[i]==0:
                    speed_list[i]=0
                elif speed_list[i]==1:
                    speed_list[i]=35
                elif speed_list[i]==2:
                    speed_list[i]=45
                elif speed_list[i]==3:
                    speed_list[i]=55
                elif speed_list[i]==4:
                    speed_list[i]=65
                elif speed_list[i]==5:
                    speed_list[i]=75
                elif speed_list[i]==6:
                    speed_list[i]=85
                else:
                    speed_list[i]=50
            direction=data.get('direction',False)
            if direction==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction_list=direction.split(',')
      
            if (len(belt_id_list)!=len(speed_list)) or (len(belt_id_list)!=len(direction_list)):
                trace.info("recv info format error")
                return {'rep': {'device': 'y', 'result': 'error'}}
            cmd_list=['aXc','bXc','cXc']
            for i in range(0,len(belt_id_list)):
                if belt_id_list[i]>=1 and belt_id_list[i]<=2:
                    cmd_list[0]+=str(belt_id_list[i])
                    cmd_list[0]+=chr(speed_list[i])
                    cmd_list[0]+=direction_list[i]
                    cmd_id_list.append(0)
                elif belt_id_list[i]>=3 and belt_id_list[i]<=4:
                    cmd_list[1]+=str(belt_id_list[i]-2)
                    cmd_list[1]+=chr(speed_list[i])
                    cmd_list[1]+=direction_list[i]
                    cmd_id_list.append(1)
                elif belt_id_list[i]>=5 and belt_id_list[i]<=6:
                    cmd_list[2]+=str(belt_id_list[i]-4)
                    cmd_list[2]+=chr(speed_list[i])
                    cmd_list[2]+=direction_list[i]
                    cmd_id_list.append(2)
                else:
                    trace.info('more than 6 belt are not support')
                    return {'rep': {'device': 'y', 'result': 'error'}}
            for i in cmd_id_list:
                command=cmd_list[i]
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                retry=2
                trace.info('%s'%command)
                for j in range(0,retry):
                    try:
                        self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                    except:
                        trace.error('send error')
                        state='error'
                    try:
                        r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                        if r==b'%cXOK\r\n'%cmd_list[i][0].encode():   
                            break
                        else:
                            trace.error('ack-->%s' %r)
                            pass
                    except:
                        state='error'
                        trace.error('no ack')
            return {'rep': {'device': 'y', 'result': state}}           
        elif cmd=='convey_belt_bailu':
            #bailu
            state='success'
            PSC=99
            cabinets=data.get('cabinets',False)
            if cabinets==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            cabinet_list=[int(i) for i in cabinets.split(',')]
            
            speed=data.get('speed',False)
            if speed==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            speed_list=[int(i) for i in speed.split(',')]
            
            for i in range(0,len(speed_list)):
                if speed_list[i]==0:
                    speed_list[i]=0
                elif speed_list[i]==1:
                    speed_list[i]=35
                elif speed_list[i]==2:
                    speed_list[i]=45
                elif speed_list[i]==3:
                    speed_list[i]=55
                elif speed_list[i]==4:
                    speed_list[i]=65
                elif speed_list[i]==5:
                    speed_list[i]=75
                elif speed_list[i]==6:
                    speed_list[i]=85
                else:
                    speed_list[i]=50
            direction=data.get('direction',False)
            if direction==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction_list=direction.split(',')
      
            if (len(cabinet_list)!=len(speed_list)) or (len(cabinet_list)!=len(direction_list)) or (len(direction_list)!=len(speed_list)):
                trace.info("recv info format error")
                return {'rep': {'device': 'y', 'result': 'error'}}
                
            cmd_list=['UXc','VXc','WXc','XXc','YXc','ZXc','[Xc']
            for i in range(0,len(cabinet_list)):
                if cabinet_list[i]>=1 and cabinet_list[i]<=4:
                    cmd_list[0]+=str(cabinet_list[i])
                    cmd_list[0]+=chr(speed_list[i])
                    cmd_list[0]+=direction_list[i]
                elif cabinet_list[i]>=5 and cabinet_list[i]<=8:
                    cmd_list[1]+=str(cabinet_list[i]-4)
                    cmd_list[1]+=chr(speed_list[i])
                    cmd_list[1]+=direction_list[i]
                elif cabinet_list[i]>=9 and cabinet_list[i]<=12:
                    cmd_list[2]+=str(cabinet_list[i]-8)
                    cmd_list[2]+=chr(speed_list[i])
                    cmd_list[2]+=direction_list[i]
                elif cabinet_list[i]>=13 and cabinet_list[i]<=16:
                    cmd_list[3]+=str(cabinet_list[i]-12)
                    cmd_list[3]+=chr(speed_list[i])
                    cmd_list[3]+=direction_list[i]
                elif cabinet_list[i]>=17 and cabinet_list[i]<=20:
                    cmd_list[4]+=str(cabinet_list[i]-16)
                    cmd_list[4]+=chr(speed_list[i])
                    cmd_list[4]+=direction_list[i]
                elif cabinet_list[i]>=21 and cabinet_list[i]<=24:
                    cmd_list[5]+=str(cabinet_list[i]-20)
                    cmd_list[5]+=chr(speed_list[i])
                    cmd_list[5]+=direction_list[i]
                elif cabinet_list[i]>=25 and cabinet_list[i]<=28:
                    cmd_list[6]+=str(cabinet_list[i]-24)
                    cmd_list[6]+=chr(speed_list[i])
                    cmd_list[6]+=direction_list[i]
                else:
                    trace.info('more than 28 cabinets are not support')
                    return {'rep': {'device': 'y', 'result': 'error'}}
            for i in range(0,(len(cmd_list))):
                if len(cmd_list[i]) >3:
                    command=cmd_list[i]
                    crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                    command = command.encode('latin-1')
                    command+= crc
                    retry=2
                    trace.info('%s'%command)
                    for j in range(0,retry):
                        try:
                            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                        except:
                            trace.error('send error')
                            state='error'
                        try:
                            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                            if r==b'%cXOK\r\n'%cmd_list[i][0].encode():   
                                break
                            else:
                                trace.error('ack-->%s' %r)
                                pass
                        except:
                            state='error'
                            trace.error('no ack')
            return {'rep': {'device': 'y', 'result': state}}    
        elif cmd=='convey_belt':
            state=0
            if self.Y_MODE=="huaqiao":
                pass
            if self.Y_MODE=="bailu":
                rev=self.process_convey_belt_old(data)
                if rev==True:
                    return {'rep': {'device': 'y', 'result': 'success'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'error'}}
            cabinet=data.get('cabinets',False)
            if cabinet==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            cabinet_list=cabinet.split(',')
            speed=data.get('speed',False)
            if speed==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            speed_list=speed.split(',')
            direction=data.get('direction',False)
            if direction==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction_list=direction.split(',')
            timeout=data.get('timeout',False)
            if timeout==False:
                timeout='40'
            motor_num=len(cabinet_list)
            if len(speed_list)!=motor_num and len(direction_list)!=motor_num:
                return {'rep': {'device': 'y', 'result': 'error'}}
            for i in range(0,motor_num):
                if cabinet_list[i]==3:
                    pass
                else:
                    rev=self.process_internal_belt(cabinet_list[i],speed_list[i],direction_list[i],timeout)
                    time.sleep(0.07)
                if rev==False:
                    trace.info("motor %s not ack"%i)
                else: 
                    state=True
            if state==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='convey_belt_old':
            state=True
            if self.Y_MODE=="huaqiao":
                pass
            if self.Y_MODE=="bailu":
                rev=self.process_convey_belt_old(data)
                if rev==True:
                    return {'rep': {'device': 'y', 'result': 'success'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'error'}}
            
            cabinet=data.get('cabinets',False)
            if cabinet==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            cabinet_list=cabinet.split(',')
            speed=data.get('speed',False)
            if speed==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            speed_list=speed.split(',')
            direction=data.get('direction',False)
            if direction==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction_list=direction.split(',')
            timeout=data.get('timeout',False)
            if timeout==False:
                timeout='40'
            motor_num=len(cabinet_list)
            if len(speed_list)!=motor_num and len(direction_list)!=motor_num:
                return {'rep': {'device': 'y', 'result': 'error'}}
            for i in range(0,motor_num): 
                rev=self.process_internal_belt(cabinet_list[i],speed_list[i],direction_list[i],timeout)
                time.sleep(0.07)
                if rev==False:
                    state=False
                    trace.info("motor %s not ack"%i)
            if state==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='convey_belt_on_huaqiao':
            direction_list=[0,0,0,0]
            speed_list=[0,0,0,0]
            group=data.get('group',False)
            if group==False:
                group=1
                #return {'rep': {'device': 'y', 'result': 'error'}}
            cabinet=data.get('cabinets',False)
            if cabinet==False:
                pass
                #return {'rep': {'device': 'y', 'result': 'error'}}
            speed = data.get('speed', False)
            if len(speed_list)!=4:
                return {'rep': {'device': 'y', 'result': 'error'}}
            direction=data.get('direction',False)
            cabinet_list=list(map(int,cabinet.split(',')))
            PSC=99
            psc = '%s' %(chr(PSC))
            
            for i in range(0,(len(cabinet_list))):
                direction_list[cabinet_list[i]-1]=direction[i]
                speed_list[cabinet_list[i]-1]=speed[i]
            i=0 
            for d in direction_list:
                if d=='l':
                    direction_list[i]=1
                else:
                    direction_list[i]=2
                i=i+1
            
            direction1 = '%s' %(chr(int(direction_list[0])))
            direction2 = '%s' %(chr(int(direction_list[1])))
            direction3= '%s' %(chr(int(direction_list[2])))
            direction4= '%s' %(chr(int(direction_list[3])))
            
            speed1 = '%s' %(chr(int(speed_list[0])))
            speed2 = '%s' %(chr(int(speed_list[1])))
            speed3 = '%s' %(chr(int(speed_list[2])))
            speed4 = '%s' %(chr(int(speed_list[3])))
            address=chr(int(group)+84)
            command= address+'X'+psc+direction1+direction2+direction3+direction4+speed1+speed2+speed3+speed4
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('%s'%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                #trace.debug('r -> %s' %r)
                if r==b'XXOKAab}\r':   
                    return {'rep': {'device': 'y', 'result': 'success'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    #trace.debug('r -> %s' %r)
                    if r==b'XXOKAab}\r':   
                        return {'rep': {'device': 'y', 'result': 'success'}}
                    else:
                        return {'rep': {'device': 'y', 'result': 'success'}}
                except:
                    trace.error('no ack')
                    return {'rep': {'device': 'y', 'result': 'error'}}
        elif cmd=='convey_belt_off':  
            command='UY'
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                #trace.debug('r -> %s' %r)
                if r==b'GYOK\xb3a\xc8\x1b\r':  
                    return {'rep': {'device': 'y', 'result': 'success'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    #trace.debug('r -> %s' %r)
                    if r==b'GYOK\xb3a\xc8\x1b\r':  
                        return {'rep': {'device': 'y', 'result': 'success'}}
                except:
                    trace.error('no ack')
                    return {'rep': {'device': 'y', 'result': 'error'}}            
        elif cmd== 'belt_power':
            cabinet=data.get("cabinet",False)
            if cabinet==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            state=data.get("state",False)
            if state==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            cmd='%s,BELT_POWER,%s,' %((chr((ord('A')+int(cabinet)-1))),state)
            crc = custom_crc32(map(ord, cmd)).to_bytes(4, 'big')
            command = cmd.encode('latin-1')
            command+= crc
            trace.info("command-->%s"%command)
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            except:
                trace.error('no ack')
                return {'rep': {'device': 'y', 'result': 'error'}}
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                #trace.debug('r -> %s' %r)
                if r==b'GYOK\xb3a\xc8\x1b\r':  
                    return {'rep': {'device': 'y', 'result': 'success'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'success'}}
            except:
                    trace.error('no ack')
                    return {'rep': {'device': 'y', 'result': 'error'}} 
        elif cmd=='sync_belt_push':
            if self.Y_MODE=="huaqiao":
                rev=self.process_sync_belt_push_huaqiao(data)
                if rev==True:
                    return {'rep': {'device': 'y', 'result': 'success'}}
                elif rev==False:
                    return {'rep': {'device': 'y', 'result': 'error'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'error','meta':rev}}
            if self.Y_MODE=="bailu":
                rev=self.process_sync_belt_push_bailu(data)
                if rev==True:
                    return {'rep': {'device': 'y', 'result': 'success'}}
                elif rev==False:
                    return {'rep': {'device': 'y', 'result': 'error'}}
                else:
                    return {'rep': {'device': 'y', 'result': 'error','meta':rev}}

            rev=self.process_sync_belt_push(data)
            if rev==True:
                return {'rep': {'device': 'y', 'result': 'success'}}
            elif rev==False:
                return {'rep': {'device': 'y', 'result': 'error'}}
            else:
                return {'rep': {'device': 'y', 'result': 'error','meta':rev}}
        elif cmd=='pcb_update':
            address=data.get('address',False)
            if address== False:
                return {'rep': {'device': 'd', 'result': 'error'}}  
            binPath = os.path.join(curDir, "Y2_Control.bin")
            command=',MCURESET'
            command=address+command
            command=command.encode()
            trace.info('cmd-->%s'%command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            time.sleep(1)
            try:
                r=self.rcomm.dev_comb.Y.q.get(timeout=3)
            except:
                return {'rep': {'device': 'y', 'result': 'error','info':'no ack'}} 
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, b'1')
            getc=YModem.getc
            putc=YModem.putc
            ymodem=YModem(getc,putc)
            trace.info('%s'%binPath)
            ymodem.send_file(binPath)
            return {'rep': {'device': 'y', 'result': 'success'}} 
        elif cmd=='reset_serial':
            ch=data.get('ch',False)
            if data == False:
                return {'rep': {'device': 'y', 'result': 'error'}}  
            rev=self.process_reset_serial(ch)
            if rev==True:
                return {'rep': {'device': 'y', 'result': 'success'}} 
            else:
                return {'rep': {'device': 'y', 'result': 'error'}}  
    def process_device_d(self,data):  
        id_ = data.get("id", None)
        if id_ is not None:
            res = self.get_res_cache(id_)
            if res is not None:
                return res
        cmd = data.get('command', False)
        if cmd is False:
            return {}
        if cmd=='hi':
            return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'hi'}})
        elif cmd=='hi_d3':
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            command='%s,HI,' %chr(int(cabinet)+64)
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('command->%s'%command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=3)
                trace.info("r--->%s"%r)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            except:
                trace.error('no ack')
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
        elif cmd=='d3_read_sw':
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            command='%s,readSW,' %chr(int(cabinet)+64)
            crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
            command = command.encode('latin-1')
            command+= crc
            trace.info('command->%s'%command)
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=3)
                trace.info("r--->%s"%r)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            except:
                trace.error('no ack')
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
        elif cmd=='read_res_cache':
            return {'rep': {'device':'d', 'result':'success','mata':self.res_cache}}
        elif cmd=='usb_err_time':
            return {'rep': {'device':'d', 'result':'success','time':int(self.checkusb.usb_err_cnt/10)}}
        elif cmd=='sync_belt_push':
            rev=self.process_sync_belt_push(data)
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if rev==True:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            elif rev==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error','cabinet':'1','mata':rev}})
        elif cmd=='cabinet_set':
            count=data.get('count',False)
            if count== False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            self.checkusb.cabinet_cnt=count    
            return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})    
        elif cmd=='push':
            cabinet=data.get('cabinet',False)
            if cabinet is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
            rev=self.process_gravity(data)
            ###
            slots=data.get('slots',False)
            if slots==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
            try:
                slot_id = list(map(int, slots.split(',')))
            except Exception as ex:
                trace.error('slot id invalid: %s' %ex)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
            trace.info('time-->%s'%(slot_id[1]/100))
            time.sleep(slot_id[1]/100+1)
            ###
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
        elif cmd =='gravity':
            cabinet=data.get('cabinet',False)
            if cabinet is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
            rev=self.process_gravity(data)
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})           
        elif cmd=='version':
            return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'d2 version 4.2.3 2020/03/17 protol add id'}})
        elif cmd=='magnet_on':   #time 200   4.5min
            cabinet=data.get('cabinet',False)
            if cabinet== False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if self.D_MODE=="D3":
                t=data.get('time',False)
                if time is False:
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
                ADDR=chr(int(cabinet)+64)
                command='%s,MAGNET_ON,%s,'%(ADDR,t)
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                trace.info('command->%s'%command)
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    trace.info("r--->%s"%r)
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
                except:
                    trace.error('no ack')
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            rev = self.process_magnet(data)
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}}) 
        elif cmd=='magnet_off':
            m_cmd_list=['EU','JU','OU']
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if self.D_MODE=="D3":
        
                ADDR=chr(int(cabinet)+64)
                command='%s,MAGNET_OFF,'%(ADDR)
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    trace.info("r--->%s"%r)
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
                except:
                    trace.error('no ack')
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
    
            num=int(cabinet)    
            cmd=m_cmd_list[num-1]
            crc = custom_crc32(map(ord, cmd)).to_bytes(4, byteorder='big')
            command=cmd.encode('latin-1')+crc
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
            try:
                rev=self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.5)
                trace.info('rev-->%s'%rev)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            except:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
        elif cmd=='led_state':
            mate=[]
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            cabinet_list=cabinet.split(',')
            for d in cabinet_list:
                mate.append('off')
            return self.set_res_cache(id_,{'rep': {'device': 'd', 'result':'success', 'meta': mate}})
        elif cmd=='led_on':
            rev=[]
            cabinet=data.get('cabinet',False)
            if cabinet== False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if self.D_MODE=="D3":
                ADDR=chr(int(cabinet)+64)
                command='%s,LED_ON,'%ADDR
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                trace.info('command->%s'%command)
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    trace.info("r--->%s"%r)
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
                except:
                    trace.error('no ack')
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
                
            cabinet_list=cabinet.split(",")
            result="success"
            for d in cabinet_list: 
                temp=self.process_led_control(d,1)
                if temp==False:
                    result="error"
                    rev.append("error")
                else:
                    rev.append("success")
            return self.set_res_cache(id_, {'rep': {'device':'d', 'result':result,'meta':rev}})
        elif cmd=='led_off':
            rev=[]
            cabinet=data.get('cabinet',False)
            if cabinet== False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
                
            if self.D_MODE=="D3":
                ADDR=chr(int(cabinet)+64)
                command='%s,LED_OFF,'%ADDR
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                try:
                    r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    trace.info("r--->%s"%r)
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
                except:
                    trace.error('no ack')
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
                    
                    
            cabinet_list=cabinet.split(",")
            result="success"
            for d in cabinet_list: 
                temp=self.process_led_control(d,0)
                if temp==False:
                    result="error"
                    rev.append("error")
                else:
                    rev.append("success")
            return self.set_res_cache(id_,{'rep': {'device': 'd', 'result':'success', 'meta': rev}})                
        elif cmd=='spring':
            rev=self.process_spring(data)
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:                        
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})                    
        elif cmd=='readJSON_test':
            rev=self.process_drop_json(2,'r')
            trace.info("rev-->%s"%rev)
            return {'rep': {'device': 'y', 'result': 'success'}}
        elif cmd=='writeJSON_test':
            rev=self.process_drop_json(2,'w','dsdsa')
            trace.info("rev-->%s"%rev)
            return {'rep': {'device': 'y', 'result': 'success'}}
        elif cmd =='spring_poll':
            rev = self.process_spring_poll(data)
            if rev=='success':
                self.spring_stop_time=time.time()
                if self.spring_stop_time-self.spring_start_time<1.5:
                    rev=self.process_spring(self.spring_data)
                    trace.info('spring error')
                    return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error','meta':'none'}})
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            if rev==None:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error','meta':'none'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error','meta':rev}})
        elif cmd =='drop_q_get_test':
            while not self.rcomm.dev_comb.DROP.q.empty():
                d = self.rcomm.dev_comb.DROP.q.get_nowait()
            return {'rep': {'device': 'd', 'result':'success', 'cabinet':'1','meta': d}}
        elif cmd=='drop_query':
            cabinet=data.get('cabinet',False)
            if cabinet is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            num=int(cabinet)    
            return {'rep': {'device': 'd', 'result':'success', 'meta': self.process_drop_json(num,'r')}}
        elif cmd == 'drop_poll':
            rev= []   
            cabinet=data.get('cabinet',False)
            num=int(cabinet)-1
            if self.checkusb.usb_poll_state[num]==0:   
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result':'success', 'cabinet':'1','meta': ['BLOCK']}})    
            while not self.rcomm.dev_comb.__dict__[self.drop[num]].q.empty():
                data = self.rcomm.dev_comb.__dict__[self.drop[num]].q.get_nowait()
                #data = data.decode('latin-1)
                if data == b'\xff\x0c\xb0\x07\x00\x00\x08\xa0\xffF\xaf\xfe':
                    rev.append('OPEN')
                    self.drop_state[int(cabinet)-1]='OPEN'
                else:
                    rev.append('BLOCK')
                    trace.warn('drop data->%s'%data)
            return self.set_res_cache(id_, {'rep': {'device': 'd', 'result':'success', 'cabinet':'1','meta': rev}}) 
        elif cmd == 'drop_check':
            rev =self.process_drop_check(data)
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})                                          
        elif cmd == 'drop_clear':
            rev=self.process_drop_clear(data)
            if rev:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})                   
        elif cmd=='drop_test':
            rev=self.process_drop_test(data)
            if rev == False:
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result':'error', 'meta':[]}})
            else:
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result':'success','meta': rev}})
        elif cmd == 'ac_poll':
            prev_t=[0,0,0]
            prev_h=[0,0,0]
            cabinet= data.get('cabinet', False)
            if cabinet is False:
                return False
            num=int(cabinet)-1
            try:        
                self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.ac[num]], b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd2')
                data = self.rcomm.dev_comb.__dict__[self.ac[num]].q.get(timeout=0.5)
            except:
                trace.info('ppppppppppp')
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'error', 'error_level': 'warning', 'meta':'no ack'}})
            if len(data) != 18:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            else:
                if (data[4]>>7)&0x01==1:
                    return self.set_res_cache(id_,{'rep': {'device':'d', 'result': 'success', 't': (data[4]<<8|data[3]-65536)/10 ,'h':(data[7]<<8|data[6])/10}})  
                else:
                    prev_t[num]=(data[4]<<8|data[3])/10
                    prev_h[num]=(data[7]<<8|data[6])/10
                    if prev_t[num]-self.ac_last_t[num]>10 or prev_h[num]-self.ac_last_h[num]>10:
                        self.ac_last_t[num]=prev_t[num]
                        self.ac_last_h[num]=prev_h[num]
                        try:        
                            self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.ac[num]], b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd2')
                            data = self.rcomm.dev_comb.__dict__[self.ac[num]].q.get(timeout=0.5)
                        except:
                            return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'error', 'error_level': 'warning', 'meta':'no ack'}})
                        if len(data) != 18:
                            return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
                        else:
                            if (data[4]>>7)&0x01==1:
                                return self.set_res_cache(id_,{'rep': {'device':'d', 'result': 'success', 't': (data[4]<<8|data[3]-65536)/10 ,'h':(data[7]<<8|data[6])/10}}) 
                            else:
                                return self.set_res_cache(id_,{'rep': {'device':'d', 'result': 'success', 't': (data[4]<<8|data[3])/10 ,'h':(data[7]<<8|data[6])/10}}) 
                    else:
                        self.ac_last_t[num]=prev_t[num]
                        self.ac_last_h[num]=prev_h[num]
                        return self.set_res_cache(id_, {'rep': {'device':'d', 'result': 'success', 't': prev_t[num], 'h': prev_h[num]}})
        elif cmd == 'RESET':
            address=data.get('address',False)
            if address==False:
                return {'rep': {'device': 'd', 'result': 'error'}}
            cmd ='RESET%s'%address
            trace.info('%s'%cmd)
            cmd=cmd.encode()
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, cmd)
            return {'rep': {'device': 'd', 'result': 'success'}}
            
        elif cmd=='ac_set':
            cabinet=data.get('cabinet',False)
            if cabinet== False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            cabinet_list=cabinet.split(',')
            mata=[]
            for i in range(0,len(cabinet_list)):  
                mata.append('error')
            rev=self.process_ac_set(data)
            if rev==True: 
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'success','mate':[]}})
            elif rev==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if rev=='1':
                mate[0]='error'
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'error','mate':mate}})
            elif rev=='2':
                mate[0]='success'
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'error','mate':mate}})
            elif rev=='3':
                mate[0]='success'
                mate[1]='success'
                return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': 'error','mate':mate}})
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})                  
        elif cmd=='ac_reset':
            mata=[]
            state='success'
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return False
            cabinet_list=cabinet.split(',')
            for d in cabinet_list:
                rev=self.process_ac_reset(d)
                if rev==False:
                    state='error'
                    mata.append('error')
                else:
                    mata.append('success')
            return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': state,'t':[12],'h':[60,75],'meta':mata}})
        elif cmd =='ac_get':
            state='success'
            meta=[]
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            t=[]
            h_min=[]
            h_max=[]
            cabinet_list=cabinet.split(',')
            for d in cabinet_list:
                num=int(d)-1
                t.append(self.process_read_ACregister(0,d)/10)
                h_min.append(self.process_read_ACregister(9,d))
                h_max.append(self.process_read_ACregister(10,d))
                trace.info('%s'%t)
                if t[num]==-1 or h_min[num]==-1 or h_max[num]==-1:
                    meta.append('error')
                    t[num]=0
                    h_min[num]=0
                    h_max[num]=0
                    state='error'
                else:
                    meta.append('success')
            return self.set_res_cache(id_, {'rep': {'device': 'd', 'result': state,'t':t,'h_min':h_min,'h_max':h_max,'meta':meta}})        
        elif cmd == 'write_ac_register':
            address=data.get('address',False)
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if address is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if cabinet=='1':
                AC_CMD=self.rcomm.dev_comb.AC
            elif cabinet=='2':
                AC_CMD=self.rcomm.dev_comb.AC1
            elif cabinet =='3':
                AC_CMD=self.rcomm.dev_comb.AC2
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            num=data.get('data',False)
            if num is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})  
            try:
                address=int(address).to_bytes(1,'big')
                num=int(num).to_bytes(1,'big')
            except:
                trace.error('address invalid: %s' %address)
                return {'rep': {'device': 'd', 'result': 'error'}}   
            cmd=b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00%c%c\x00\x00' %(address,num)   
            crc8 = crcmod.predefined.Crc('crc-8-maxim')
            crc8.update(cmd)
            c=crc8.crcValue.to_bytes(1,'big')
            cmd=cmd+c
            trace.info('%s' %cmd)     
            try:
                self.rcomm.dev_send(AC_CMD, cmd)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'success'}})
            except:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})          
        elif cmd =='read_ac_register':
            address=data.get('address',False)
            cabinet=data.get('cabinet',False)
            if cabinet==False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if address is False:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            if cabinet=='1':
                AC_CMD=self.rcomm.dev_comb.AC
            elif cabinet=='2':
                AC_CMD=self.rcomm.dev_comb.AC1
            elif cabinet =='3':
                AC_CMD=self.rcomm.dev_comb.AC2
            else:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})
            try:
                address=int(address)
                address=address.to_bytes(1,'big')
            except:
                trace.error('address invalid: %s' %address)
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})   
            cmd=b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%c\x00\x00\x00' %(address)   
            crc8 = crcmod.predefined.Crc('crc-8-maxim')
            crc8.update(cmd)
            c=crc8.crcValue.to_bytes(1,'big')
            cmd=cmd+c
            trace.info('%s' %cmd) 
            try:
                self.rcomm.dev_send(AC_CMD, cmd)
                data= AC_CMD.q.get(timeout=2)
                ac_register_data =data[14]
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result': 'success', 'data':'%s' %ac_register_data}})
                return {'rep': {'device':'d', 'result': 'success', 'data':'%s' %ac_register_data}}
            except:
                return self.set_res_cache(id_, {'rep': {'device':'d', 'result':'error'}})         
        elif cmd=='PCB_version':            
            rev = self.process_pcbversion(data)
            if rev:
                return {'rep': {'device':'d', 'result':'success'}}
            else:
                return {'rep': {'device': 'd', 'result': 'error'}}  
        elif cmd=='pcb_update':
            address=data.get('address',False)
            if address== False:
                return {'rep': {'device': 'd', 'result': 'error'}} 
            version=data.get('version',False)
            if version==False:
                return {'rep': {'device': 'd', 'result': 'error'}} 
            if version=='old':
                binPath = os.path.join(curDir, "d_v1.1.1.bin")
            else:
                binPath = os.path.join(curDir, "d_v2.1.1.bin")
            command='RESET'
            command+=address
            command=command.encode()
            trace.info('cmd-->%s'%command)
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
            time.sleep(1)
            try:
                r=self.rcomm.dev_comb.GRAVITY.q.get(timeout=3)
            except:
                return {'rep': {'device': 'd', 'result': 'error','info':'no ack'}} 
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, b'1')
            time.sleep(0.1)
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, b'2')
            time.sleep(0.6)
            self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, b'1')
            getc=YModem.getc
            putc=YModem.putc
            ymodem=YModem(getc,putc)
            trace.info('%s'%binPath)
            ymodem.send_file(binPath)
            return {'rep': {'device': 'd', 'result': 'success'}} 
        elif cmd=='reset_serial':
            ch=data.get('ch',False)
            if data == False:
                return {'rep': {'device': 'd', 'result': 'error'}}  
            rev=self.process_reset_serial(ch)
            if rev==True:
                return {'rep': {'device': 'd', 'result': 'success'}} 
            else:
                return {'rep': {'device': 'd', 'result': 'error'}}  
        else:
            return {'rep': {'device': 'd', 'result':'error', 'error_level':'warning', 'meta':'unknow command'}}
    def process_run(self,data):   #end PCB firmware download
        command='a'
        command=command.encode()
        self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
    def process_pcbversion(self,data):
        address=data.get('address',False)
        if address==False:
            return False
        command='%sV'%address
        crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
        command = command.encode('latin-1')
        command+= crc
        trace.info('%s' %command)
        self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
        try:
            r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.5)
            #trace.debug('r -> %s' %r)
        except:
            trace.error('no ack')
            return False
            #return {'rep': {'device': 'd', 'result': 'error'}}
        return True                            
    def process_led_control(self,cabinet,state):
        led_cmd_list=[b'EL\x07\xbd\xb7\x1a',b'JR\xcd(\xe0r',b'OT\xbeWI\xce',b'EM\x03|\xaa\xad',b'JS\xc9\xe9\xfd\xc5',b'OO\xd9\rY\xdf']#led_on1,led_on2,led_on3,led_off1,led_off2,led_off3
        mata=[]
        if state==1:
            command=led_cmd_list[int(cabinet)-1]
        else:
            command=led_cmd_list[int(cabinet)+3-1]
        self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
        try:
            r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.5)
            trace.debug('r -> %s' %r)
            return True
        except:
            trace.error('no ack')
            return False
            #return {'rep': {'device': 'd', 'result': 'error'}}
    def process_gravity(self, data):
        slot_id = data.get('slots', False)
        if slot_id is False:
            return False
        cabinet=data.get('cabinet',False)
        if cabinet is False:
            return False
        cabinet=int(cabinet) 
        try:
            slot_id = list(map(int, slot_id.split(',')))
        except Exception as ex:
            trace.error('slot id invalid: %s' %ex)
            return False
        
        if len(slot_id) % 2 != 0:
            trace.error('slot id invalid')
            return False
        
        cmd_group = ['AD', 'BD', 'CD', 'DD', 'ED','FD','GD','HD','ID','JD','KD','LD','MD','ND','OD']
        for i in range(len(slot_id)//2):
            s = slot_id[i*2]
            delay = slot_id[i*2+1] // 5
            if delay ==0:
                delay=1
            h = (s // 100) & 0xff
            if h > 10:
                trace.error('h is too large')
                return False
            v = (s - h*100) & 0xff
            s = '%s%s' % (chr(v), chr(delay))
            
            cmd_group[h-1+(cabinet-1)*5] += s

        trace.debug('cmd_group -> %s' %cmd_group)

        for cmd in cmd_group:
            if len(cmd) > 2:
                crc = custom_crc32(map(ord, cmd)).to_bytes(4, 'big')
                cmd = cmd.encode('latin-1')
                cmd += crc
                trace.debug('curr cmd ----> %s' %cmd)
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, cmd)
                except:
                    pass
                try: 
                    r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.25)
                    trace.info('gravity command 1')
                    #trace.debug('r -> %s' %r)
                except:
                    trace.error('no ack')
                    return False
        return True
    def process_magnet(self,data):
        cabinet=data.get('cabinet',False)
        if cabinet is False:
            trace.error('cabinet error')
            return False
        t=data.get('time',False)
        if t is False:
            trace.error('time error')
            return False
        cabinet1_cmd='EX'
        cabinet2_cmd='JY'
        cabinet3_cmd='OZ'
        cabinet1_resp=b'EDOK\xc7\xaeDi\r\n'
        cabinet2_resp=b'JDOK\x0e4=1\r\n'
        cabinet3_resp=b'ODOKIB\x15\xf9\r\n'
        if cabinet=='1':
            rev=self.bucket_get(cabinet1_cmd,t,cabinet1_resp)
            if rev:
                return True
            else:
                return False
        elif cabinet=='2':
            rev=self.bucket_get(cabinet2_cmd,t,cabinet2_resp)
            if rev:
                return True
            else:
                return False
        elif cabinet=='3':
            rev=self.bucket_get(cabinet3_cmd,t,cabinet3_resp)
            if rev:
                return True
            else:
                return False
        elif cabinet=='all':
            rev=self.bucket_get(cabinet2_cmd,t,cabinet2_resp)
            trace.info('lock 2 %s' %rev)
            rev=self.bucket_get(cabinet3_cmd,t,cabinet3_resp)
            trace.info('lock 3 %s' %rev)
            rev=self.bucket_get(cabinet1_cmd,t,cabinet1_resp)
            trace.info('lock 1 %s' %rev)
            return rev
        else:
            trace.info("magnet cabinet is wrong")
            return False
    def process_spring_a(self, data):
        slot_id = data.get('slot_id', False)
        if slot_id is False:
            trace.error('no slot id')
            return
        try:
            slot_id = int(slot_id)
            slot_id = slot_id.to_bytes(1, 'big')
        except:
            trace.error('slot id invalid: %s' %slot_id)
            return False

        cmd = b'\xfa\xfe\x01%c\x01\xff\xda\xef' %(slot_id)
        trace.info('curr cmd -> %s' %cmd)

        if self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, cmd) is False:
            trace.error('failed to write')
            return False
        else:            
            return True 
    def process_spring_b(self, data):
        slot_id = data.get('slot_id', False)
        if slot_id is False:
            trace.error('no slot id')
            return False
        try:
            slot_id = int(slot_id)
            slot_id = slot_id.to_bytes(1, 'big')
        except:
            trace.error('slot id invalid: %s' %slot_id)
            return False

        cmd = b'\xfa\xfe\x01%c\x01\xff\xda\xef' %(slot_id)
        trace.info('curr cmd -> %s' %cmd)

        if self.rcomm.dev_send(self.rcomm.dev_comb.SPRING, cmd) is False:
            trace.error('failed to write')
            return False
        else:
            return True   
    def process_spring(self,data):
        rev=''
        cabinet=data.get('cabinet',False)
        if cabinet is False:
            trace.error('cabinet error')
            return False
        shelf=data.get('shelf',False)
        if shelf is False:
            trace.error('shelf error')
            return False
        slot_id=data.get('slot_id',False)
        if slot_id is False:    
            trace.error('slot_id error')
            return False
            
        if self.rcomm.spring_select_mode_flag==1:
            if shelf=='l':
                #trace.info('old d1 l')
                rev=self.process_spring_a(data)
                return rev
            elif shelf=='r':
                #trace.info('old d1 r')
                rev=self.process_spring_b(data)
                return rev
            else:
                trace.error('spring shelf id error')
                return False
        if shelf=='l':
            shelf_id=1
        elif shelf=='r':
            shelf_id=2
        else:
            trace,error('spring shelf id error')
            return False
        
        spring_address=(int(cabinet)-1)*2+shelf_id-1
        try:
            slot_id = int(slot_id)
            slot_id = slot_id.to_bytes(1, 'big')
            spring_address=spring_address.to_bytes(1,'big')
        except:
            trace.error('slot id invalid: %s' %slot_id)
            return False
        
        cmd = b'\xfa\xfe%c%c\x01\xff\xda\xef' %(spring_address,slot_id)
        trace.info('curr cmd -> %s' %cmd)
        if self.rcomm.dev_send(self.rcomm.dev_comb.SPRING, cmd) is False:
            trace.error('failed to write')
            return False
        else:            
            return True 
    def process_spring_poll_b(self):
        try:
            data = self.rcomm.dev_comb.SPRING.q.get(timeout=0.125)
            trace.info('%s' %data)
            if data == b'\x02\x01\x01':
                return 'no_motor' #.decode('latin-1')
            elif data== b'\x03\x01':
                return 'cmd_err' #.decode('latin-1')
            else:
                return 'success' #.decode('latin-1')
            return 'success' #.decode('latin-1')
        except:
            return None 
    def process_spring_poll_a(self):
        try:
            data = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.125)
            trace.info('%s' %data)
            if data == b'\x02\x01\x01':
                return 'no_motor' #.decode('latin-1')
            elif data== b'\x03\x01':
                return 'cmd_err' #.decode('latin-1')
            else:
                return 'success' #.decode('latin-1')
            return 'success' #.decode('latin-1')
        except:
            return None
    def process_spring_poll(self,data):
        cabinet=data.get('cabinet',False)
        if cabinet is False:
            trace.info('cabinet error')
            return False
        shelf =data.get('shelf',False)
        if shelf is False:
            trace('cabinet error') 
            return False
        if shelf=='l':
            shelf_id=1
        else:
            shelf_id=2
        spring_address=(int(cabinet)-1)*2+shelf_id-1     
        try:
            spring_address=spring_address.to_bytes(1,'big')
        except:
            trace.error('slot id invalid: %s' %slot_id)
            return False 
        if self.rcomm.spring_select_mode_flag==0:
            try:
                data = self.rcomm.dev_comb.SPRING.q.get(timeout=0.125)
                trace.info('%s' %data)
                if data == b'\x02\x01%c' %spring_address:
                    return 'no_motor' #.decode('latin-1')
                elif data== b'\x03%c' %spring_address:
                    return 'cmd_err' #.decode('latin-1')
                else:
                    return 'success' #.decode('latin-1')
                return 'success' #.decode('latin-1')
            except:
                return None   
        else:
            if shelf=='l':
                try:
                    data = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.125)
                    trace.info('%s' %data)
                except:
                    return None
            else:
                try:
                    data = self.rcomm.dev_comb.SPRING.q.get(timeout=0.125)
                    trace.info('%s' %data)
                except:
                    return None
            if data == b'\x02\x01\x01':
                return 'no_motor' #.decode('latin-1')
            elif data== b'\x03\x01':
                return 'cmd_err' #.decode('latin-1')
            elif data==b'\x00\x01':
                return 'success' #.decode('latin-1')
            else:
                return None
    def process_internal_belt(self,cabinet,speed,direction,timeout):   
        if int(speed)==0:
            speed=0    
        else:
            speed=int(speed)*10+35        

        address=chr(int(cabinet)+64)
        cmd = '%s,%s,%s,%s,%s,' %(address,'BELT',direction,str(speed),timeout)
        crc = custom_crc32(map(ord, cmd)).to_bytes(4, byteorder='big')
        cmd = cmd.encode()
        cmd += crc
        trace.info('cmd -> %s' %cmd)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=0.2)
            trace.info("r--->%s"%r)
        except:
            trace.error('no ack')
            return False 
        return True        
    def process_sync_belt_push(self,data):
        rev=[]
        slot_id=[]
        delay_cmd=''
        cabinet=data.get('cabinet',False)
        slot_list=data.get('slots',False)
        if slot_list is False:
            return False
        if cabinet is False:
            return False  
        address=chr(int(cabinet)+64) 
        
        for d in slot_list:
            num=int(d['slot_no'])
            num=(101//100-1)*12+num%100
            slot_id.append(int(d['slot_no']))
            delay_cmd+=str(num)+'|'+str(d['stop_delay'])+'!'
            
        #trace.info("delay_cmd-->%s"%delay_cmd)
        delay_cmd=delay_cmd.rstrip('!')
        #trace.info("slot_id-->%s"%slot_id)
        bit_map=[0,0,0,0,0,0]
        for i in slot_id:
            temp=(i%100)+(i//100-1)*12
            m=temp//8
            n=temp%8
            if n==0:
                bit_map[m-1]=bit_map[m-1]|0x80
            else:
                bit_map[m]=bit_map[m]|(1<<(n-1))
            if m>12:
                return False 
        trace.info(bit_map)
        j=0
        for i in bit_map:
            if i == 0:
                bit_map[j]='00'
            elif i>>4==0:
                bit_map[j]='0'+hex(bit_map[j])[2:]
            elif i<<4==0:
                bit_map[j]=hex(bit_map[j])[2:]+'0'
            else:
                bit_map[j]=hex((bit_map[j]&0xf0)>>4)[2:]+hex(bit_map[j]&0x0f)[2:]
            j=j+1
        
        cmd = '%s,%s,%s,%s_%s_%s_%s_%s_%s,' %(address,'PUSH',delay_cmd,bit_map[5],bit_map[4],bit_map[3],bit_map[2],bit_map[1],bit_map[0])
        crc = custom_crc32(map(ord, cmd)).to_bytes(4, byteorder='big')
        cmd = cmd.encode()
        cmd += crc
        trace.info('cmd -> %s' %cmd)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=3)
            trace.info("r--->%s"%r)
        except:
            trace.error('no ack')
            return False
        if r==b'%s,PUSH,OK\r\n' %(address.encode()):
            return True
        else:
            list_temp=r.split(b',')
            trace.info('list-->%s'%list_temp)
            
            try:
                l=len(list_temp[3])
                
                for i in range(0,l):
                    if list_temp[3][i]%12==0:
                        temp_h=list_temp[3][i]//12
                        shelve_id=100*temp_h+12
                    else:
                        temp_h=list_temp[3][i]//12+1
                        shelve_id=100*temp_h+list_temp[3][i]%12
                    rev.append(shelve_id)
            except:
                return False
            trace.info('motor run err num %s' %rev)
            return rev
        return True 
    def process_sync_belt_push_huaqiao(self,data):
        rev=[]
        cabinet=data.get('cabinet',False)
        slot_id=data.get('slot_id',False)
        if slot_id is False:
            return False
        if cabinet is False:
            return False
        try:
            slot_id = list(map(int,slot_id.split(',')))
        except Exception as ex:
            trace.error('slot id is invalid:%s' %ex)
            return False
        bit_map=[0,0,0,0,0]
        for i in slot_id:
            temp=(i%100)+(i//100-1)*12
            m=temp//8
            n=temp%8
            if n==0:
                bit_map[m-1]=bit_map[m-1]|0x80
            else:
                bit_map[m]=bit_map[m]|(1<<(n-1))
            if m>12:
                return False 
        trace.info(bit_map)

        j=0
        for i in bit_map:
            if i == 0:
                bit_map[j]='00'
            elif i>>4==0:
                bit_map[j]='0'+hex(bit_map[j])[2:]
            elif i<<4==0:
                bit_map[j]=hex(bit_map[j])[2:]+'0'
            else:
                bit_map[j]=hex((bit_map[j]&0xf0)>>4)[2:]+hex(bit_map[j]&0x0f)[2:]
            j=j+1
        cmd = '%s,%s,%s_%s_%s_%s_%s_%s,' %( chr(int(cabinet)+64),'PUSH',bit_map[5],bit_map[4],bit_map[3],bit_map[2],bit_map[1],bit_map[0])
        crc = custom_crc32(map(ord, cmd)).to_bytes(4, byteorder='big')
        cmd = cmd.encode()
        cmd += crc
        trace.info('cmd -> %s' %cmd)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=3)
        except:
            trace.error('no ack')
            return False
        trace.info('r->%s'%r)
        if r==b'Z,PUSH,OK,9d6f31d7\r\n':
            return True
        else:
            list_temp_a=r.split(b',')
            try:
                list_temp_b=list_temp_a[3].split(b'_')
            except:
                False
            for i in range(len(list_temp_b)-1):
                idata=bstr2int(list_temp_b[i])
                rev.append(idata)    
            trace.info('motor run err num %s' %rev)
            return rev
        return True 
    def process_sync_belt_push_bailu(self,data):
        rev=[]
        delay=data.get('delay',False)
        delay=2
        cabinet=data.get('cabinet',False)
        slot_id=data.get('slot_id',False)
        if slot_id is False:
            return False
        if cabinet is False:
            return False  
        address=chr(int(cabinet)+64)
        try:
            slot_id = list(map(int,slot_id.split(',')))
        except Exception as ex:
            trace.error('slot id is invalid:%s' %ex)
            return False
        bit_map=[0,0,0,0,0,0]    
        for i in slot_id:
            temp=(i%100)+(i//100-1)*12
            m=temp//8
            n=temp%8
            if n==0:
                bit_map[m-1]=bit_map[m-1]|0x80
            else:
                bit_map[m]=bit_map[m]|(1<<(n-1))
            if m>12:
                return False 
        trace.info(bit_map)
        
        j=0
        for i in bit_map:
            if i == 0:
                bit_map[j]='00'
            elif i>>4==0:
                bit_map[j]='0'+hex(bit_map[j])[2:]
            elif i<<4==0:
                bit_map[j]=hex(bit_map[j])[2:]+'0'
            else:
                bit_map[j]=hex((bit_map[j]&0xf0)>>4)[2:]+hex(bit_map[j]&0x0f)[2:]
            j=j+1
            
        cmd = '%s,%s,%s,%s_%s_%s_%s_%s_%s,' %(address,'PUSH',chr(delay),bit_map[5],bit_map[4],bit_map[3],bit_map[2],bit_map[1],bit_map[0])
        crc = custom_crc32(map(ord, cmd)).to_bytes(4, byteorder='big')
        cmd = cmd.encode()
        cmd += crc
        trace.info('cmd -> %s' %cmd)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=3)
            trace.info("r--->%s"%r)
        except:
            trace.error('no ack')
            return False
        if r==b'D,PUSH,TIMEOUT,\r,\r\n':
            trace.info('timeout')
            return False
        if r.startswith(b'%s,PUSH'%address.encode()):  #r==b'%s,PUSH,OK\r\n' %(address.encode()):
            return True
        else:
            list_temp=r.split(b',')
            trace.info('list-->%s'%list_temp)
            
            try:
                l=len(list_temp[3])
                
                for i in range(0,l):
                    if list_temp[3][i]%12==0:
                        temp_h=list_temp[3][i]//12
                        shelve_id=100*temp_h+12
                    else:
                        temp_h=list_temp[3][i]//12+1
                        shelve_id=100*temp_h+list_temp[3][i]%12
                    rev.append(shelve_id)
            except:
                return False
            trace.info('motor run err num %s' %rev)
            return rev
        return True 
    def process_drop_clear(self,data):
        cabinet = data.get('cabinet', False)
        num=int(cabinet)-1
        if cabinet is False:
            return False
        try:
            self.rcomm.dev_flush(self.rcomm.dev_comb.__dict__[self.drop[num]])
            self.rcomm.dev_comb.__dict__[self.drop[num]].q.queue.clear()
            return True
        except:
            return False
    def process_drop_check(self,data):
        state=''
        cabinet=data.get('cabinet',False)
        if cabinet is False:
            self.rcomm.dev_comb.DROP.q.queue.clear()
            drop_flag=0
            s=b'\xff\x06\xb0\xfb\xa0' 
            for i in range(0,6):
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.DROP,b'\xff\x07\xb0\x01\x01\x01\x00\x04\xd3\xfe') 
                    r = self.rcomm.dev_comb.DROP.q.get(timeout=0.5)
                    if len(r)>=2:
                        time.sleep(2)
                        try:              
                            self.rcomm.dev_comb.DROP.q.queue.clear()
                            self.rcomm.dev_flush(self.rcomm.dev_comb.DROP)
                            trace.info('drop_check rep ?')
                            return True
                        except:
                            return True
                except:
                    trace.error('no ack')
            return False
        attr=int(cabinet)-1
        self.rcomm.dev_comb.__dict__[self.drop[attr]].q.queue.clear()
        s=self.process_drop_json(int(cabinet),r='r')
        trace.info('%s'%s)
        for i in range(0,3):
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.drop[attr]],b'\xff\x07\xb0\x01\x01\x01\x00\x04\xd3\xfe') 
                r = self.rcomm.dev_comb.__dict__[self.drop[attr]].q.get(timeout=0.5)
                trace.info('%s' %r)
                if len(r)>=2:
                    time.sleep(3)
                    try:           
                        self.rcomm.dev_comb.__dict__[self.drop[attr]].q.queue.clear()
                        self.rcomm.dev_flush(self.rcomm.dev_comb.__dict__[self.drop[attr]])
                        self.process_drop_json(int(cabinet),r='w',state=s)
                        return True
                    except:
                        return True
            except:
                trace.error('no ack')
        return False   
    def process_convey_belt_old(self,data):
        PSC=99
        cabinets=data.get('cabinets',False)
        if cabinets==False:
            return False
        cabinet_list=[int(i) for i in cabinets.split(',')]
            
        speed=data.get('speed',False)
        if speed==False:
            return False
        speed_list=[int(i) for i in speed.split(',')]
        direction=data.get('direction',False)
        if direction==False:
            return False
        direction_list=direction.split(',')  
          
        for i in range(0,len(speed_list)):
            if speed_list[i]==0:
                speed_list[i]=0
            elif speed_list[i]>=1 or speed_list[i]<=6:
                speed_list[i]=25+speed_list[i]*10
            else:
                speed_list[i]=50

        if (len(cabinet_list)!=len(speed_list)) or (len(cabinet_list)!=len(direction_list)) or (len(direction_list)!=len(speed_list)):
            trace.info("recv info format error")
            return False
        cmd_list=['UXc','VXc','WXc','XXc','YXc','ZXc','[Xc']
        for i in range(0,len(cabinet_list)):
            if cabinet_list[i]>=1 and cabinet_list[i]<=4:
                cmd_list[0]+=str(cabinet_list[i])
                cmd_list[0]+=chr(speed_list[i])
                cmd_list[0]+=direction_list[i]
            elif cabinet_list[i]>=5 and cabinet_list[i]<=8:
                cmd_list[1]+=str(cabinet_list[i]-4)
                cmd_list[1]+=chr(speed_list[i])
                cmd_list[1]+=direction_list[i]
            elif cabinet_list[i]>=9 and cabinet_list[i]<=12:
                cmd_list[2]+=str(cabinet_list[i]-8)
                cmd_list[2]+=chr(speed_list[i])
                cmd_list[2]+=direction_list[i]
            elif cabinet_list[i]>=13 and cabinet_list[i]<=16:
                cmd_list[3]+=str(cabinet_list[i]-12)
                cmd_list[3]+=chr(speed_list[i])
                cmd_list[3]+=direction_list[i]
            elif cabinet_list[i]>=17 and cabinet_list[i]<=20:
                cmd_list[4]+=str(cabinet_list[i]-16)
                cmd_list[4]+=chr(speed_list[i])
                cmd_list[4]+=direction_list[i]
            elif cabinet_list[i]>=21 and cabinet_list[i]<=24:
                cmd_list[5]+=str(cabinet_list[i]-20)
                cmd_list[5]+=chr(speed_list[i])
                cmd_list[5]+=direction_list[i]
            elif cabinet_list[i]>=25 and cabinet_list[i]<=28:
                cmd_list[6]+=str(cabinet_list[i]-24)
                cmd_list[6]+=chr(speed_list[i])
                cmd_list[6]+=direction_list[i]
            else:
                trace.info('more than 28 cabinets are not support')
                return False
        for i in range(0,(len(cmd_list))):
            if len(cmd_list[i]) >3:
                command=cmd_list[i]
                crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
                command = command.encode('latin-1')
                command+= crc
                retry=2
                trace.info('%s'%command)
                for j in range(0,retry):
                    try:
                        self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
                    except:
                        trace.error('send error')
                        state=False
                    try:
                        r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                        if r==b'%cXOK\r\n'%cmd_list[i][0].encode():  
                            return True 
                            break
                        else:
                            trace.error('ack-->%s' %r)
                            pass
                    except:
                        state=False
                        trace.error('no ack')
        return False        
    def process_drop_test(self,data):
        cabinet=data.get('cabinet',False)
        if cabinet==False:
            return False
        cabinet_list=cabinet.split(',')
        mata=[]
        for i in range(0,len(cabinet_list)):    
            mata.append('')
        for d in cabinet_list:
            num=int(d)-1
            try:
                if self.rcomm.dev_comb.__dict__[self.drop[num]].q.qsize()==0:
                    mata[num]=''
            except:
                trace.info('drop1 queue error')
                mata[num]=''
                return mata
            while not self.rcomm.dev_comb.__dict__[self.drop[num]].q.empty():
                data = self.rcomm.dev_comb.__dict__[self.drop[num]].q.get_nowait()
                #data = data.decode('latin-1)
                mata[num]=''
                if data == b'\xff\x0c\xb0\x07\x00\x00\x08\xa0\xffF\xaf\xfe':
                    mata[num]='00000000'
                if data[7]==0x0f:
                    temp=data[8]
                    for i in range(0,8):
                        if temp&0x01==0:
                            mata[num]=mata[num]+'1'
                        else:
                            mata[num]=mata[num]+'0'
                        temp=temp>>1
        return mata
        
    def process_write_ACregister(self,address,t,cabinet):
        num=int(cabinet)-1
        data_temp=t
        ac_register_data=0
        try:
            address=address.to_bytes(1,'big')
            t=int(t).to_bytes(1,'big')
        except:
            trace.error('address invalid: %s' %address)
            return False
        cmd=b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00%c%c\x00\x00' %(address,t)   
        crc8 = crcmod.predefined.Crc('crc-8-maxim')
        crc8.update(cmd)
        c=crc8.crcValue.to_bytes(1,'big')
        cmd=cmd+c
        trace.info('%s' %cmd)     
        try:
            self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.ac[num]], cmd)
            time.sleep(0.05)
            cmd=b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%c\x00\x00\x00' %(address)       
            crc8 = crcmod.predefined.Crc('crc-8-maxim')
            crc8.update(cmd)
            c=crc8.crcValue.to_bytes(1,'big')
            cmd=cmd+c
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.ac[num]], cmd)
                t_list= self.rcomm.dev_comb.__dict__[self.ac[num]].q.get(timeout=2)
                if len(t_list)!=18:
                    return False
                ac_register_data =t_list[14]
                if ac_register_data==data_temp:
                    return True
                else:
                    return False
            except:
                return False
        except:
            return False            
            
    def process_read_ACregister(self,address,cabinet):
        num=int(cabinet)-1
        cmd=b'\x5a\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%c\x00\x00\x00' %(address)       
        crc8 = crcmod.predefined.Crc('crc-8-maxim')
        crc8.update(cmd)
        c=crc8.crcValue.to_bytes(1,'big')
        cmd=cmd+c
        try:
            self.rcomm.dev_send(self.rcomm.dev_comb.__dict__[self.ac[num]], cmd)
            t_list= self.rcomm.dev_comb.__dict__[self.ac[num]].q.get(timeout=2)
            if len(t_list)!=18:
                return -1
            ac_register_data =t_list[14]
            return ac_register_data
        except:
            return -1
    def process_ac_set(self,data):
        mata=[]
        state='success'
        t_list=data.get('t',False)
        if t_list==False:
            return False
            
        h_min_list=data.get('h_min',False)
        if h_min_list==False:
            return False
                
        h_max_list=data.get('h_max',False)
        if h_max_list==False:
            return False
                
        cabinet=data.get('cabinet',False)
        if cabinet==False:
            return False
        cabinet_list=cabinet.split(',')
            
        for d in cabinet_list:
            if d=='1':
                h_min=h_min_list[0]
                h_max=h_max_list[0]
                t=t_list[0]*10
            elif d=='2':
                h_min=h_min_list[1]
                h_max=h_max_list[1]
                t=t_list[1]*10
            elif d=='3':
                h_min=h_min_list[2]
                h_max=h_max_list[2]
                t=t_list[2]*10
            else:
                trace.info('cabinet error')
                return {'rep': {'device': 'd', 'result': 'error'}} 
            rev=self.process_write_ACregister(0,t,d)
            if rev==False:
                return d
            rev=self.process_write_ACregister(9,h_min,d)
            if rev==False:
                return d
            rev=self.process_write_ACregister(10,h_max,d)
            if rev==False:
                return d
        return True
    def bucket_get(self,cmd,time,ack):
        t=chr(time)
        command=cmd+t
        crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
        command = command.encode('latin-1')
        command+= crc
        trace.info('command-->%s'%command)
        self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
        try:
            r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.2)
            trace.debug('r -> %s' %r)
            if r==ack:
                trace.info('1')
                return True
            else:
                trace.info('wrong ack')
                return True                  
        except:
            try:
                self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
                r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.2)
                trace.debug('r -> %s' %r)
                if r==ack:
                    trace.info('2')
                    return True
                else:
                    trace.info('wrong ack')
                    return True
            except:
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
                    r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.2)
                    trace.debug('r -> %s' %r)
                    if r==ack:
                        trace.info('3')
                        return True
                    else:
                        trace.info('wrong ack')
                        return True
                except:
                    try:
                        self.rcomm.dev_send(self.rcomm.dev_comb.GRAVITY, command)
                        r = self.rcomm.dev_comb.GRAVITY.q.get(timeout=0.2)
                        trace.debug('r -> %s' %r)
                        if r==ack:
                            trace.info('4')
                            return True
                        else:
                            trace.info('wrong ack')
                            return True
                    except:
                        trace.error('no ack')
                        return False
    def process_ac_reset(self,cabinet):
        t=[]
        h=[]
        r=''
        r=self.process_read_ACregister(0,cabinet)
        if r==-1:
            return False
        data=int(r)
        data=data/10
        t.append(data)
        r=self.process_read_ACregister(9,cabinet)
        if r==-1:
            return False
        data=int(r)
        h.append(data)
        r=self.process_read_ACregister(10,cabinet)
        if r==-1:
            return False
        data=int(r)
        h.append(data)
        reg_data_list=[[0,120],[1,30],[3,3],[4,12],[5,8],[6,8],[9,53],[10,60],[11,20],[12,15],[13,60],[14,75],[15,4],[16,20],[17,2],[18,0],[22,1],[23,1]]
        for l in reg_data_list:
            address=l[0]
            data=l[1]
            r=self.process_write_ACregister(address,data,cabinet)
            if r==False:
                return False
        #trace.info('t:%s,h:%s'%t%h)
        return True
    def process_pc_start_set_ac(self):
        usb=[]
        write_cmd=b'Z\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x17\x01\x00\x00\xf0'
        read_cmd=b'Z\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x17\x00\x00\x00l' 
        try:
            usb=os.listdir('/dev/serial/by-id/') 
        except:
            pass
        for d in usb:
            if d == 'usb-fusionRobotics_D1_b0001-if03-port0':
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC, write_cmd)
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC, read_cmd)
                    ac_temp=self.rcomm.dev_comb.AC.q.get(timeout=0.5)
                    trace.info('AC %s'%ac_temp)
                    if ac_temp[14]==1:
                        trace.info('ac ok')
                except:
                    trace.info('ac error')
                    pass
            elif d=='usb-fusionRobotics_D2_b0001-if02-port0':
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC1, write_cmd)
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC1, read_cmd)
                    ac_temp=self.rcomm.dev_comb.AC1.q.get(timeout=0.5)
                    trace.info('AC1 %s'%ac_temp)
                    if ac_temp[14]==1:
                        trace.info('ac1 ok')
                except:
                    trace.info('ac1 error')
                    pass
            elif d== 'usb-fusionRobotics_D2_b0001-if03-port0':
                try:
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC2, write_cmd)
                    self.rcomm.dev_send(self.rcomm.dev_comb.AC2, read_cmd)
                    ac_temp=self.rcomm.dev_comb.AC2.q.get(timeout=0.5)
                    trace.info('AC2 %s'%ac_temp)
                    if ac_temp[14]==1:
                        trace.info('ac2 ok')
                except:
                    trace.info('ac2 error')
                    pass
    def process_drop_json(self,cabinet,r='r',state='open'):
        json_err=0
        jsonPath = os.path.join(curDir, "d2.json")
        drop_list=['drop_1','drop_2','drop_3']
        if r=='r':
            while json_err==0:
                f=open(jsonPath,encoding='utf-8')
                content=f.read()
                try:
                    trace.info('d2.json 1')
                    user_dict = json.loads(content)
                    trace.info('d2.json 2')
                    json_err=1
                except:
                    with open(jsonPath, "w") as jsonFile:
                        data={"drop_2": "OPEN", "drop_3": "OPEN", "drop_1": "OPEN"}
                        trace.info('d2.json 3')
                        json.dump(data, jsonFile,ensure_ascii=False)
                        trace.info('d2.json 4')
            if user_dict[drop_list[cabinet-1]]=='BLOCK' or user_dict[drop_list[cabinet-1]]=='OPEN':
                return user_dict[drop_list[cabinet-1]]
            else:
                trace.error('json error-->%s'%user_dict[drop_list[cabinet-1]])
                return 'BLOCK'
        else: 
            with open(jsonPath, "r",encoding='utf-8') as jsonFile:
                data=json.load(jsonFile)
                data[drop_list[cabinet-1]]=state
            with open(jsonPath, "w") as jsonFile:
                json.dump(data, jsonFile,ensure_ascii=False)
            return True
    def process_usb_init(self):
        count=1
        self.drop_state[0]=self.process_drop_json(1,'r')
        trace.info('drop1-->%s'%self.drop_state[0])
        self.drop_state[1]=self.process_drop_json(2,'r')
        trace.info('drop2-->%s'%self.drop_state[1])
        self.drop_state[2]=self.process_drop_json(3,'r')
        trace.info('drop3-->%s'%self.drop_state[2])
        while self.usb_state:
            count+=1
            if count==20:
                trace.info('usb reset')
                os.system('sudo /home/fusion/kiosk/sbin/fuckusb /dev/bus/usb/001/002')
                time.sleep(3)
                os.system('/home/fusion/kiosk/bin/rotate.sh')
            time.sleep(0.1)
            try:
                listdir=os.listdir('/dev/serial/by-id/') 
                if 4<=len(listdir)<=6:
                    if listdir.count('usb-fusionRobotics_D1_b0001-if00-port0'):
                        if listdir.count('usb-fusionRobotics_D1_b0001-if01-port0'):
                            if listdir.count('usb-fusionRobotics_D1_b0001-if02-port0'):
                                if listdir.count('usb-fusionRobotics_D1_b0001-if03-port0'):
                                    self.usb_state=0
                                    trace.info('single machine')
                elif len(listdir)>6:
                    if listdir.count('usb-fusionRobotics_D1_b0001-if00-port0'):
                        if listdir.count('usb-fusionRobotics_D1_b0001-if01-port0'):
                            if listdir.count('usb-fusionRobotics_D1_b0001-if02-port0'):
                                if listdir.count('usb-fusionRobotics_D1_b0001-if03-port0'):
                                    if listdir.count('usb-fusionRobotics_D2_b0001-if00-port0'):
                                        if listdir.count('usb-fusionRobotics_D2_b0001-if01-port0'):
                                            if listdir.count('usb-fusionRobotics_D2_b0001-if02-port0'):
                                                if listdir.count('usb-fusionRobotics_D2_b0001-if03-port0'):
                                                    self.usb_state=0
                                                    trace.info('mult machine')
                else:
                    pass
            except:
                trace.info('usb error')
    def open(self, block=True, timeout=3, retry=3):
        rev=''
        if self.ex_is_opened():
            trace.info('ex already opened')
            return True
        for i in range(retry):
            rev = self.goto_para(-1100, 0.0012,0.001,0.01, (100,150,250), (1500,100,250,500), # 1112
                                flag=self.EX_FLAG['EX_OPEN'], block_check=block, tolerance=10, timeout=timeout, retry=1)
            trace.debug('goto rev: %s' %rev)
            if not block:
                return
            
            if rev is False:
                trace.warning('commu error or jam?')
            else:
                if rev < 20:
                    return True

            if self.ex_is_opened():
                trace.info('qd failed but sensor ready, maybe home needed')
                return True
            else:
                continue
        
        return False
     
    def sensor_parse(self, data):
        data = data.split('|')
        if len(data) != 5:
            return False
        try:
            rev = map(int, data)
        except Exception as ex:
            return False
        bm = dict( zip(self.sensor_bm, rev) )
        return bm      
    def goto_para(self, pos, start_speed, end_speed, const_speed, k_a, k_d, duty, 
                    block_check=False, timeout=10, retry=2, wait_first=False):
        
        parameters = '%s|%s|%s|%s|%s|%s|%s' %(pos, start_speed, end_speed, const_speed, k_a, k_d, duty)
        data=bytes()
        #trace.debug('parameters -> %s' %parameters)
        for i in range(retry):
            
            if i == 0 and wait_first and block_check:
                pass
            else:
                trace.info('(%s) goto: %d' %(self.addr, pos))
                self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'p', parameters)
                try:
                    data=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                    trace.info('data-->%s'%data)
                except:
                    pass
                data=data.decode('latin-1')
                if not data.startswith('%cpp' %(self.addr)):
                    trace.debug('unexpected result(%c%s): %s' %(self.addr, 'pp', repr(data)))
                    time.sleep(0.05)
                    continue
            
            if block_check:
                rev = self.poll_wait_state([[0,1], [0,2]], timeout, interval=0.05)
                if rev is not True:
                    trace.error('%s rev not true?? (%s)' %(self.addr, rev))
                    self.idle()
                    time.sleep(0.1)
                
                curr_qd = self.qd_read()
                delta = curr_qd - pos
                trace.info('(%s) stop @ %d(%d)' %(self.addr, self.qd_read(), delta))
                if abs(delta) <= 10:
                    return delta
                else:
                    trace.info('(%s) goto failed? retry count: %d' %(self.addr, i))
                    self.idle()
                    time.sleep(0.1)
            else:
                return pos
        
        return False    
    def sensor(self, retry=3,board='door_board'):
        if board=='door_board':
            addr='x'
        elif board=='ex_board':
            addr='y'
        else:
            return False
        rev=bytes()
        for i in range(retry):
            self.rcomm.send(addr,self.rcomm.dev_comb.Y,'I', '')
            try:
                rev=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.info('rev-->%s'%rev)
            except:
                pass
            rev=rev.decode('latin-1')
            if rev.startswith('%sI'%addr):
                trace.info('before rev parse->%s'%rev[2:len(rev)-2])
                rev = self.sensor_parse(rev[2:len(rev)-2])
                if rev is False:
                    trace.error('failed to parse sensor..(%s)' %(rev))
                    continue
                else:
                    return rev
            else:
                trace.error('unexpected result(%c%s): %s' %(self.addr, 'I..', repr(rev)))
                time.sleep(i*0.02)
        return {}
    def homed(self):
        data = self.sensor()
        if data is False or type(data) is not dict:
            trace.error('data format error? (%s)' %(data))
            return False
        else:
            data = data.get('GEAR')
            
            if data == 0x01:
                return True
            else:
                return False
    def ex_is_closed(self):
        return self.homed()
    
    def ex_is_opened(self):
        data = self.sensor()
        if data is False or type(data) is not dict:
            trace.error('data format error? (%s)' %(data))
            return False
        else:
            data = data.get('GEAR')
            
            if data==3:
                return True
            else:
                return False
    def ex_door_watch_start(self, retry=3):
        for i in range(retry):
            time.sleep(i*0.02)
            data = self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'W', 's', timeout=0.25)
            if data == '%cWs' %(self.addr):
                return True
        return False
    def close(self, block=True, timeout=6, retry=3, delay=2):
        if self.ex_is_closed():
            trace.info('ex already closed')
            return True
        
        for i in range(retry):
            if self.sensor().get('DOOR', 0):
                trace.info('DOOR sensor detect..no move')
                time.sleep(delay)
                continue
            
            self.ex_door_watch_start()
            rev = self.goto_para(8, 0.00125,0.001,0.01, (200,300,350,500), (600,200,250,300,350),
                            flag=self.EX_FLAG['EX_CLOSE'], block_check=True, retry=1, timeout=timeout, tolerance=5)
            trace.debug('goto rev: %s' %rev)
            if not block:
                return
            
            if rev is False:
                trace.warning('commu error or jam?')
            else:
                if rev < 20:
                    return True
            trace.info('poll -> %s' %self.poll_long())
            trace.info('ex_door watch -> %s' %self.ex_door_watch_read())
            
            if self.ex_is_closed():
                trace.info('qd failed but sensor ready')
                return True
            
            self.ex_open(block=False)
            time.sleep(delay)
        
        return False
        """ for block_check mode, return ---> False or delta
        for non block_check, return ---> target pos
    """
    def poll_wait_state(self, s, timeout=30, interval=0.1):
        start = time.time()
        while time.time() - start < timeout:
            rev = self.poll()
            for d in s:
                if d==rev:
                    return True
            else:
                #print rev
                time.sleep(interval)
        return [False, rev]
    def idle(self, retry=6):
        for i in range(retry):
            time.sleep(i*0.02)
            self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'0')
            try:
                data=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.info('data-->%s'%data)
                data=data.decode('latin-1')
                if data.startswith('%c00' %(self.addr)):
                    time.sleep(0.1)
                    return True
                else:
                    trace.error('unexpected result(%c%s): %s' %(self.addr, '00', repr(data)))
            except:
                pass
        return False
    def qd_read(self, retry=6):
        rev=''
        for i in range(retry):
            time.sleep(i*0.02)
            self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'Q', 'R', timeout=0.25)
            try:
                rev=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                rev=rev.decode('latin-1')
                trace.info('rev-->%s'%rev)
                if rev.startswith('%cQR' %(self.addr)):
                    try:
                        return int(rev[3:len(rev)-2])
                    except:
                        continue
            except:
                    pass
        trace.debug('failed to query qd, data: %s' %(str(rev)))
        return False
    def qd_clear(self, retry=3):
        rev=''
        for i in range(retry):
            time.sleep(i*0.02)
            self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'Q', 'R', timeout=0.25)
            try:
                rev=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                rev=rev.decode('latin-1')
                trace.info('rev-->%s'%rev)
                if rev.startswith('%cQR' %(self.addr)):
                    return True
            except:
                    pass
        trace.debug('failed to query qd, data: %s' %(str(rev)))
        return False

    def ex_open(self, block=True, timeout=3, retry=3):
        if self.is_opened():
            trace.info('ex already opened')
            return True
        
        for i in range(retry):
            # rev = self.goto_para(-1080, 0.0012,0.001,0.01, (100,150,250), (500,100,250,300), # 1112
            #flag=self.EX_FLAG['EX_OPEN'], block_check=block, tolerance=10, timeout=timeout, retry=1)
            rev = self.goto_para(-1105, 120, 100, 600, 7.5, -2.5, 0, block_check=block, retry=1, timeout=5)
            trace.debug('goto rev: %s' %rev)
            if not block:
                return
            
            if rev is False:
                trace.warning('commu error or jam?')
            else:
                if rev < 20:
                    return True
        return False  
    def ex_close(self, block=True,door_check=True, timeout=8, retry=3):
        if self.is_closed():
            trace.info('already closed')
            return True
        for i in range(retry):
            self.goto_para(50, 320, 100, 800, 2.5, -0.5, 1000, block_check=False)
            rev = False
            start = time.time()
            while time.time() - start < timeout:
                ss = self.sensor()
                #print ss
                if door_check==True:
                    if ss.get('DOOR', 2) == 1:
                        self.idle()
                        self.ex_open(block=False)
                        time.sleep(1.5)
                        rev = False
                        break
                    #if ss.get('GEAR', 0x01) == 0x01:
                    #elif ss.get('GEAR', 0x01)==3:
                    #    rev = True
                    #    self.idle()
                    elif ss.get('GEAR', 0x01)==2:
                        rev = True
                        self.idle()
                        break
                    elif ss.get('GEAR', 0x01)==1:
                        rev = True
                        self.idle()
                        break
                    else:
                        rev=False
                        #break
                    #else:
                    #    if self.poll == [0,1]:
                    #        rev = False
                else:
                    if ss.get('GEAR', 0xff) == 0x01:
                        rev = True
                        self.idle()
                        break
                    else:
                        if self.poll == [0,1]:
                            rev = False
            trace.debug('goto rev: %s' %rev)
            if not block:
                return
            
            if rev is False:
                trace.warning('commu error or jam?')
            else:
                if rev < 20:
                    if self.is_closed():
                        return True
                    else:
                        if self.home(300, check=True):
                            return True

                self.goto_para(self.qd_read()-100, 200, 100, 500, 2.5, -0.5, 0, block_check=True, retry=1, timeout=5)

            #self.open(block=False)
            time.sleep(.2)
        
        return False
    def is_closed(self):
        return self.homed()
    
    def is_opened(self):
        if self.sensor().get('GEAR', 0xff) == 0x02:
            return True
        else:
            return False
    def poll(self, retry=6):
        data=bytes()
        for i in range(retry):
            time.sleep(i*0.05)
            self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'?', '')
            try:
                data=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.info('data-->%s'%data)
            except:
                pass
            data=data.decode('latin-1')
            if not data.startswith('%c?' %(self.addr)):
                if i > 2:
                    trace.error('poll (%s) failed? (retry:%d) %s' %(self.addr, i, repr(data)))
                continue
            rev = self.poll_parse(data[2:len(data)-2])
            trace.info('poll rev-->%s'%rev)
            if rev:
                return rev
            else:
                trace.error('failed to parse: %s' %(data))
        return False
    def poll_parse(self, data):
        data = data.split('|')
        if len(data) != 2:
            return False
        try:
            rev = list(map(int, data))
            return rev
        except Exception as ex:
            return False
    def home(self, spd, check=False, retry=5, timeout=6):
        data=bytes()
        assert type(spd) is int
        for i in range(retry):
            self.rcomm.send(self.addr,self.rcomm.dev_comb.Y,'o', '%d' %(spd))
            try:
                data=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.info('data-->%s'%data)
            except:
                pass
            data=data.decode('latin-1')
            trace.info('data-->%s'%data)
            if data.startswith('%coo'%self.addr):
                if check:
                    self.poll_wait_state(([0,1], [0,2]), timeout=timeout, interval=0.1)
                    if self.homed():
                        return True
                    else:
                        trace.error('check homed failed, retry..')
                        self.idle()
                        time.sleep(0.25)
                        continue
                return True
            else:
                trace.error('unexpected result(%c%s): %s' %(self.addr, 'OO', repr(data)))
                self.idle()
                time.sleep(0.05)
        return False
    def led(self, rgb_list):
        para=''
        l = len(rgb_list)
        if l % 3 != 0:
            trace.error('grb list len not match')
            return False
        para = '%s' %(chr(int(l/3))) +''.join(map(chr, rgb_list))
        for i in range(3):
            self.rcomm.send('y',self.rcomm.dev_comb.Y,'L', para=para )
            try:
                data=self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                data=data.decode('latin-1')
                if not data.startswith('ycL' ):
                    continue
                else:
                    return True
                trace.info('data-->%s'%data)
            except:
                pass
        return False
        
    def get_res_cache(self, id_):
        return self.res_cache.get(id_, {}).get("res", None)

    def set_res_cache(self, id_, res):
        if id_ != "":
            res["rep"]["id"] = id_
        # remove the timeout cache
        item=self.res_cache.items()
        
        for cache_id in list(self.res_cache):
            cache_res=self.res_cache[cache_id]
            try:
                if time.time() - cache_res["time"] > self.res_cache_timeout:
                    del self.res_cache[cache_id]
            except:
                pass
        self.res_cache[id_] = {"res": res, "time": time.time()}
        return res
        
    def process_rst_serial(self,data):
        CMD_BIT=1
        STATE_BIT=2
        SUM_BIT=3
        cmd_list=[0x53,0x01,0x02,0x56]
        serial_id=data.get('serial_id',False)
        if serial_id==False:
            return False
        state=data.get('state',False)
        if state==False:
            return False
        cmd_list[CMD_BIT]=int(serial_id)
        if state=="OFF":
            cmd_list[STATE_BIT]=1
        else:
            cmd_list[STATE_BIT]=2
        cmd_list[SUM_BIT]=cmd_list[0]+cmd_list[1]+cmd_list[2]
        cmd_list=list(map(chr,cmd_list))
        for i in range(0,4):
            cmd+=cmd_list[i]
        cmd=cmd.encode('latin-1')    
    def m3_process_open_lock(self,data):
        lock_id=data.get('lock_id',False)
        if lock_id ==False:
            return False
        lock_id=int(lock_id)    
        if lock_id<108 and lock_id >100:
            num=lock_id-100
        elif lock_id<205 and lock_id >200:
            num=7+lock_id-200
        elif lock_id==205:
            num=12
        elif lock_id<210 and lock_id >205:
            num=7+4+2+lock_id-205
        elif lock_id<313 and lock_id >300:
            num=7+4+2+4+lock_id-300
        elif lock_id<416 and lock_id >400:
            num=7+4+2+4+12+lock_id-400
        else:
            return False
        trace.info('lock_id--->%d'%num)
        command='EM%c'%num
        crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
        command=command.encode('latin-1')
        command=command+crc
        trace.info('cmd-->%s'%command)
        try:
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
            if r.startswith(b'EM'):
                time.sleep(0.5)
                if self.m3_check_sensor(num)=='0':  #open
                    return True
                else:
                    trace.info('Lattice not open')
                    return False
            else:
                False
        except:
            trace.error('no ack')
            return False
    def m3_check_sensor(self,sensor_id):
        command='Es%c'%(int(sensor_id))
        crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
        command=command.encode('latin-1')
        command=command+crc
        trace.info('cmd-->%s'%command)
        try:
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
            #trace.debug('r -> %s' %r)
            if r.startswith(b'Es'):
                return chr(r[2])
            else:
                return False
        except:
            trace.error('no ack')
            return False
        return {'rep': {'device': 'm3', 'result': 'success'}}    
    def m3_open_rgb_led(self,data):
        led_dict={'101':5,'105':6,'106':7,'201':8,'202':9,'203':10,'204':11,'208':13,'209':14,'301':17,'302':18,'303':19,'304':20,'305':21,'402':22,'404':23,'405':24,'410':25,'412':26,'403':27,'406':28,'409':29}
        led_id=data.get('led_id',False)
        if led_id==False:
            return False
        led_id=led_dict.get(led_id,False)
        if led_id==False:
            return False
        rgb=data.get('colour',False)
        if led_id==False:
            return False
        s = '%s%s' % (chr(int(rgb)),chr(led_id))
        command='AN'+s
        crc = custom_crc32(map(ord, command)).to_bytes(4, 'big')
        command = command.encode('latin-1')
        command+= crc
        trace.info('%s' %command)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
            trace.debug('r -> %s' %r)
        except:
            trace.error('no ack')
            return False
        return True
    def process_reset_serial(self,ch):
        rev=rstserial.RstSerial(int(ch))
        return rev
    def m3_lattice_led_control(self,data,retry=3):
        colour=data.get('colour',False)
        if colour==False:
            return False
        led_ids=data.get('led_ids',False)
        if led_ids==False:
            return False
        led_list=led_ids.split(',')
        cmd_id=3
        cmd='l'+chr(cmd_id)+chr(43)+chr(len(led_list))+chr(colour[0])+chr(colour[1])+chr(colour[2])
        for d in led_list:
            if int(d) in range(101,108):#1~7
                cmd=cmd+chr(int(d)-100)
            elif int(d) in range(201,209):#8~15
                cmd=cmd+chr(16-(int(d)-200))
            elif int(d) in range(301,313):#16~28
                cmd=cmd+chr(int(d)-300+15)
            elif int(d) in range(401,416):#29~43
                cmd=cmd+chr(43-(int(d)-400))
            else:
                return False
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'lLED'):
                    return True
            except:
                trace.error('no ack')
                return False
        return False
    def m3_lattice_led_clear(self,retry=3):
        cmd='l'+chr(6)
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'lCLEAR'):
                    return True
            except:
                trace.error('no ack')
                return False
        return False
    def m3_lattice_close_all_led(self,retry=3):
        cmd='l'+chr(7)
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'lCLOSE'):
                    return True
            except:
                trace.error('no ack')
                return False
        return False
    def m3_lattile_lock_driver_process(self,data):
        lock_ids=data.get('lock_id',False)
        if lock_ids ==False:
            return False
        lock_list=list(map(int,lock_ids.split(',')))
        if len(lock_list)>2:
            trace.info('max lock is 2')
            return False
        lock_para=chr(len(lock_list))
        for d in lock_list:
            d=(d//100-1)*16+d%100
            lock_para=lock_para+chr(d) 
        return lock_para
    def m3_gen_frame(self,board_addr,command,xl9535_addr,para,retry=2):
        cmd=board_addr+command+xl9535_addr+para
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'%s%sok' %(board_addr.encode(),command.encode())):
                    return True
                else:
                    trace.error('error ack')
            except:
                trace.error('no ack')
                return False
        return False
    def m3_lid_control_process(self,data,retry=3):
        ch_list=data.get('ch',False)
        if ch_list==False:
            return False
        ch_len=len(ch_list) 
        cmd='OC%c'%ch_len
        back_duty=3
        wait_time=10
        for d in range(0,ch_len):
            cmd+=chr(int(ch_list[d]))
            cmd+=chr(back_duty)
            cmd+=chr(wait_time)
            
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                trace.debug('r -> %s' %r)
                if r.startswith(b'OC'):
                    return True
            except:
                trace.error('no ack')
                return False
        return False
    def m3_lid_poll_process(self,data,retry=3):
        cmd='OS'
        
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                r=r.decode('latin-1')
                trace.debug('r -> %s' %r)
                if r.startswith('OS'):
                    return r[3]
            except:
                trace.error('no ack')
                return False
        return False
    def m3_drop_cup(self,data,retry=3):
        delay_list=data.get('delay')
        duty=data.get('duty')
        cmd='OP'+chr(int(duty))+chr(delay_list[0])+chr(delay_list[1])
        
        cmd = cmd.encode('latin-1')
        crc = struct.pack('H', self.crc_func(cmd))
        cmd+= crc
        trace.info('%s' %cmd)
        for i in range(0,retry):
            self.rcomm.dev_send(self.rcomm.dev_comb.Y, cmd)
            try:
                r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
                r=r.decode('latin-1')
                trace.debug('r -> %s' %r)
                if r.startswith('OP'):
                    return True
            except:
                trace.error('no ack')
                return False
        return False
    def m3_pcb_version(self,data):
        board=data.get('board',False)
        if board==False:
            return {'rep': {'device': 'm3', 'result': 'error'}}
        if board =='lattice':
            command='lV'
        if board == 'beans':
            command='OV'
        command = command.encode('latin-1')
        crc = struct.pack('H', self.crc_func(command))
        command+= crc    
        trace.info('%s' %command)
        self.rcomm.dev_send(self.rcomm.dev_comb.Y, command)
        try:
            r = self.rcomm.dev_comb.Y.q.get(timeout=0.5)
            trace.debug('r -> %s' %r)
            return r[1:5].decode('latin-1')
        except:
            trace.error('no ack')
            return False

def main():
    daemon = Daemon()
    daemon.start()
    while 1:
        time.sleep(1)
    
######################
if __name__ == "__main__":
    
    main()
