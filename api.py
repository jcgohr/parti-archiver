from urls import *
from functions import split_parti_url
import requests
import json

def getUserId(platform:str,username:str)->bool:
    resp=requests.get(USER_ID_ENPOINT.format(platform,username))
    return resp.content.decode()

def isLive(user_id:str)->bool:
    resp=requests.get(LIVE_INFO_ENDPOINT.format(user_id))
    return json.loads(resp.content)["is_streaming_live_now"]

if __name__=="__main__":
    print(isLive(getUserId(*split_parti_url("https://parti.com/creator/parti/worldoftshirts2001"))))
    
