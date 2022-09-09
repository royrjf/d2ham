#!/usr/bin/python3

import os
import sys
import time
import threading
import logging

import zmq

class Serv( threading.Thread ):
    def __init__(self, trace, gui_port=1124, term_port=9527, pub_port=6666):
        super(Serv, self).__init__()
        self.trace = trace
        self._stop_event = threading.Event()
        self.GUI_PORT = gui_port
        self.TERM_PORT = term_port
        self.PUB_PORT = pub_port
        self.context = zmq.Context()
        self.gui_sock = self.context.socket(zmq.REP)
        self.gui_sock.setsockopt(zmq.RCVTIMEO,1)
        self.term_sock = self.context.socket(zmq.REP)
        self.term_sock.setsockopt(zmq.RCVTIMEO,1)
        self.pub_sock = self.context.socket(zmq.PUB)
    
    def join(self, timeout=1):
        self._stop_event.set()
        super(Serv, self).join(timeout)
    
    def run(self):
        self.gui_sock.bind('tcp://0.0.0.0:%d' %(self.GUI_PORT))
        self.term_sock.bind('tcp://0.0.0.0:%d' %(self.TERM_PORT))
        self.pub_sock.bind('tcp://0.0.0.0:%d' %(self.PUB_PORT))
        
        last_heatbeat = time.time()
        log_time_10min = time.time()
        while not self._stop_event.is_set():
            if self.gui_sock.poll(10):
                self.process_gui_hook(self.gui_sock)
            if self.term_sock.poll(5):
                self.process_term_hook(self.term_sock)
            if time.time() - last_heatbeat > 1:
                self.process_heatbeat(self.pub_sock)
                last_heatbeat = time.time()
            if time.time()-log_time_10min > 600:
                log_time_10min = time.time()
                self.trace.info('serv heatbeat')
        self.context.destroy()
        #trace.info('SERV TERMINATED')
        return
    
    def process_gui_hook(self, gui_sock):
        """override the func, handle gui msg
        """
        try:
            data = gui_sock.recv_json()
            #trace.debug('gui msg: %s' %(data))
        except:
            #trace.error('failed to got json')
            gui_sock.send_json({})
            return False
        gui_sock.send_json('ok (got %s)' %(data))
        
    def process_term_hook(self, term_sock):
        """override the func, handle term msg
        """
        try:
            data = term_sock.recv_json()
            #trace.debug('term msg: %s' %(data))
        except:
            #trace.error('failed to got json')
            term_sock.send_json({})
            return False
        term_sock.send_json('ok (got %s)' %(data))
        
    def process_heatbeat(self, pub_sock):
        try:
            pub_sock.send_json({'type':'heatbeat', 'ts':time.ctime()})
        except:
            trace.error('failed to send json: %s' %(ex))
            pass
##########################
if __name__ == '__main__':
    serv = Serv()
    serv.start()
    
    while serv.is_alive():
        time.sleep(1)


