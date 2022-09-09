#!/usr/bin/python3
import os
import sys
import zmq
import time
def test():
    context = zmq.Context(); socket = context.socket(zmq.REQ); socket.connect('tcp://127.0.0.1:7651') 
    socket.send_json({'req': {'device':'d', 'command':'PCB_version','cabinet':'1','address':'A'}}); print(socket.recv_json())
    socket.send_json({'req': {'device':'d', 'command':'PCB_version','cabinet':'1','address':'B'}}); print(socket.recv_json())
    socket.send_json({'req': {'device':'d', 'command':'PCB_version','cabinet':'1','address':'C'}}); print(socket.recv_json())
    socket.send_json({'req': {'device':'d', 'command':'PCB_version','cabinet':'1','address':'D'}}); print(socket.recv_json())
    socket.send_json({'req': {'device':'d', 'command':'PCB_version','cabinet':'1','address':'E'}}); print(socket.recv_json())
    while 1:
        for i in range(1,2):
            for j in range(1,6):
                for k in range(101,141):
                    time.sleep(1)
                    socket.send_json({'req': {'device':'d', 'command':'gravity','cabinet':'%s'%i,'slots':'%s,100'%(k+(j-1)*100)}}); print(socket.recv_json())
                    
                    
