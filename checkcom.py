#!/usr/bin/python3

import os
import sys
import time
import fcntl
import serial
import select
import termios
import logging
import threading
import json
from queue import Queue
import conf
import platform

class Checkusb( threading.Thread ):
    def __init__(self, trace):
        super(Checkusb, self).__init__()
        self.trace = trace
        self._stop_event = threading.Event()
        self.cabinet_cnt=1
        
        self.usb_err_cnt=0
        self.usb_poll_state=[1,1,1]
        self.usb_disconnect_cnt=0
        self.usb_reset_cnt=0
    def join(self, timeout=1):
        self._stop_event.set()
        super(Checkusb, self).join(timeout)
        
    def fkcusb(self,data):
        self.trace.info('reset usb %s times' %data)
        os.system('sudo /home/fusion/kiosk/sbin/fuckusb /dev/bus/usb/001/002')
        time.sleep(3)
        os.system('/home/fusion/kiosk/bin/rotate.sh')    
    def check_usb(self,usb):
        usb_cnt=0
        serial_list=os.listdir('/dev/serial/by-id')
        if usb=='master':
            for d in serial_list:
                if d.count('usb-fusionRobotics_D1') == 1:
                    usb_cnt+=1
        if usb == 'slave':
            for d in serial_list:
                if d.count('usb-fusionRobotics_D2') == 1:
                    usb_cnt+=1
        if usb_cnt == 4:
            return True
        else:
            return False
    def read_usb_disconnect_time(self):
        return int(self.usb_disconnect_cnt/10)
    def run(self):
        usb1=0
        usb2=0
        self.trace.info('hello checkcom')
        pcname=platform.node()
        
        if pcname.find('rui'):
            pass
        elif pcname.find('Y'):
            pass
        elif pcname.find('D2'):
            while not self._stop_event.is_set():
                time.sleep(0.1)
                if self.cabinet_cnt == 1:
                    if self.check_usb('master') ==True :
                        self.usb_err_cnt=0
                        self.usb_poll_state[0]=0
                        pass
                    else:
                        self.usb_poll_state[0]=1
                        self.usb_usb_err_cnt+=1
                        if self.usb_err_cnt == 10:
                            if usb_reset_cnt == 1:
                                start_time=time.time()
                                while 1:
                                    time.sleep(1)
                                    curr_time=time.time()
                                    if curr_time-start_time>1800:
                                        usb_reset_cnt=0        
                            self.usb_err_cnt=0
                            self.usb_reset_cnt+=1
                            trace.info('checkusb fuckusb')
                            self.fuckusb(self.usb_reset_cnt)
                        self.usb_disconnect_cnt+=1
                else:
                    if self.check_usb('master') ==True :
                        self.usb_err_cnt=0
                        self.usb_poll_state[0]=0
                        pass
                    else:
                        self.usb_poll_state[0]=1
                        self.usb_usb_err_cnt+=1
                        if self.usb_err_cnt == 10:
                            if usb_reset_cnt == 1:
                                start_time=time.time()
                                while 1:
                                    time.sleep(1)
                                    curr_time=time.time()
                                    if curr_time-start_time>1800:
                                        usb_reset_cnt=0   
                            self.usb_err_cnt=0
                            self.usb_reset_cnt+=1
                            trace.info('checkusb fuckusb')
                            self.fuckusb(self.usb_reset_cnt)
                        self.usb_disconnect_cnt+=1
                    if self.check_usb('slave') ==True :
                        self.usb_err_cnt=0
                        self.usb_poll_state[1]=0
                        self.usb_poll_state[2]=0
                        pass
                    else:
                        self.usb_poll_state[1]=1
                        self.usb_poll_state[2]=1
                        self.usb_usb_err_cnt+=1
                        if self.usb_err_cnt == 10:
                            if usb_reset_cnt == 3:
                                pass
                            self.usb_err_cnt=0
                            self.usb_reset_cnt+=1
                            trace.info('checkusb fuckusb')
                            self.fuckusb(self.usb_reset_cnt)
                        self.usb_disconnect_cnt+=1
                    
        else:
            while not self._stop_event.is_set():
                time.sleep(0.1)
        
            
            
