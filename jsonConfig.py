#!/usr/bin/python3
import os
import sys
import json
import platform

def readJson(jsonName):
    curDir = os.path.abspath(os.path.dirname(__file__))
    jsonPath = os.path.join(curDir, jsonName)
    print(jsonPath)
    f=open(jsonPath,encoding='utf-8')
    content=f.read()
    try:
        conf_dict = json.loads(content)
        return conf_dict
    except:
        return False

def writeJsonData(jsonName,data): 
    curDir = os.path.abspath(os.path.dirname(__file__))   
    jsonPath = os.path.join(curDir, jsonName)
    
    with open(jsonPath, "w") as jsonFile:
        json.dump(data, jsonFile,ensure_ascii=False)

def writeDropState(jsonName,cabinet,state):
    curDir = os.path.abspath(os.path.dirname(__file__))   
    jsonPath = os.path.join(curDir, jsonName)    
    with open(jsonPath, "r",encoding='utf-8') as jsonFile:
        data=json.load(jsonFile)
        data['drop_state'][cabinet-1]=state
    with open(jsonPath, "w") as jsonFile:
        json.dump(data, jsonFile,ensure_ascii=False)

def writeDropStates(jsonName,drop_state_list):
    curDir = os.path.abspath(os.path.dirname(__file__))   
    jsonPath = os.path.join(curDir, jsonName) 
    with open(jsonPath, "r",encoding='utf-8') as jsonFile:
        data=json.load(jsonFile)
        data['drop_state']=drop_state_list
    with open(jsonPath, "w") as jsonFile:
        json.dump(data, jsonFile,ensure_ascii=False)
        
def readDropStates(jsonName):
    data=readJson(jsonName)
    return data['drop_state']   
    
def readDevice(jsonName,device):
    data=readJson(jsonName)
    return data[device] 
    
