"""Client using the threading API."""

from websockets.sync.client import connect
from api import getUserId, isLive
from urls import PARTI_WS_URI
import json
import logging
import os
import threading
import time
import traceback

logger = logging.getLogger("websockets")
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())


headers={
    # "Host": "ws-backend.parti.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-WebSocket-Version": "13",
    "Origin": "https://parti.com",
    "Sec-WebSocket-Extensions": "permessage-deflate",
    "Connection": "keep-alive, Upgrade",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "websocket",
    "Sec-Fetch-Site": "same-site",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Upgrade": "websocket"
}

def safe_save_chat(msgs, filepath, is_partial=False):
    """Save chat messages safely with error handling"""
    try:
        # Make sure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # First write to a temporary file
        temp_path = f"{filepath}.tmp"
        with open(temp_path, "w", encoding="utf-8") as chat_file:
            chat_file.write(json.dumps(msgs, indent=4, ensure_ascii=False))
            # Make sure data is written to disk
            chat_file.flush()
            os.fsync(chat_file.fileno())
        
        # Then rename to the final file (atomic operation)
        os.replace(temp_path, filepath)
        
        file_type = "partial" if is_partial else "final"
        print(f"Successfully saved {len(msgs)} messages to {file_type} chat file: {filepath}")
        return True
    except Exception as e:
        print(f"Error saving chat data to {filepath}: {e}")
        traceback.print_exc()
        return False

def parti_chat(platform, username, path, stop_event=None):
    """
    Monitor Parti chat with graceful termination support
    
    Args:
        platform: The platform name
        username: The username to follow
        path: Directory to save chat logs
        stop_event: Threading event that signals when to stop
    """
    msgs = []
    user_id = int(getUserId(platform, username))
    
    # Default to a never-triggering event if none provided
    if stop_event is None:
        stop_event = threading.Event()
    
    # Define file paths
    partial_file = os.path.join(path, "chat_partial.json")
    final_file = os.path.join(path, "chat.json")
    
    # Save partial results periodically in case of crash
    def save_partial_results():
        return safe_save_chat(msgs, partial_file, is_partial=True)
    
    last_save_time = time.time()
    save_interval = 15  # Save every 15 seconds
        
    try:
        with connect(PARTI_WS_URI, additional_headers=headers) as websocket:
            # Set a timeout so we can periodically check the stop_event
            websocket.timeout = 1.0  # 1 second timeout
            
            # Subscribe to the chat
            websocket.send(json.dumps({"subscribe_options":{"ChatPublic":{"user_id": user_id}}}))
            print(f"Connected to chat for user {user_id}")
            
            # Process messages until told to stop
            while not stop_event.is_set():
                try:
                    msg = websocket.recv()
                    print(f"Chat message received: {msg[:100]}...")  # Print first 100 chars
                    msgs.append(json.loads(msg))
                    
                    # Periodic save
                    current_time = time.time()
                    if current_time - last_save_time > save_interval:
                        save_partial_results()
                        last_save_time = current_time
                        
                except TimeoutError:
                    # This is expected due to our timeout - just continue and check stop_event
                    # Also check if stream is still live as a backup exit condition
                    if not isLive(user_id):
                        print("Stream is no longer live, preparing to exit chat collection")
                        # Don't exit immediately, give it a few more tries to collect final messages
                        if len(msgs) == 0 or time.time() - last_save_time > 30:
                            print("No recent messages, exiting chat collection")
                            break
                    continue
                except Exception as e:
                    print(f"Error in WebSocket connection: {e}")
                    break
    except Exception as e:
        print(f"Error establishing WebSocket connection: {e}")
    finally:
        # Save all collected messages to file
        if msgs:
            # Try to save final results
            if not safe_save_chat(msgs, final_file):
                # If saving to final file fails, try one more time with a different filename
                backup_file = os.path.join(path, f"chat_backup_{int(time.time())}.json")
                print(f"Trying backup save to {backup_file}")
                safe_save_chat(msgs, backup_file)
        else:
            print("Chat monitoring stopped, no messages collected")
    
    return msgs

if __name__ == "__main__":
    test_dir = "test_chat_output"
    os.makedirs(test_dir, exist_ok=True)
    parti_chat("parti", "hairyape", test_dir)