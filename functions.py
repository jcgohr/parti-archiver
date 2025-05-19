from urllib.parse import urlparse,quote_plus

import re

def split_parti_url(link:str)->tuple[str,str]:
    segments=link[len("https://parti.com/creator/"):].split("/")
    print(segments)
    if len(segments)>2:
        # this requires some strange url encoding, probably liable to break in the future
        return [segments[0]]+[segments[1]+quote_plus("#"+segments[2])]
    return segments


if __name__=="__main__":
    url1 = "https://parti.com/creator/discord/buddy_christ/0"

    social1, username1 = split_parti_url(url1)
    print(f"URL: {url1}, Social Media: {social1}, Username: {username1}")

    url2 = "https://parti.com/creator/parti/worldoftshirts2001"
    social2, username2 = split_parti_url(url2)
    print(f"URL: {url2}, Social Media: {social2}, Username: {username2}")