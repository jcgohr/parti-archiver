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

# Configure logger - actual level will be set by archiver.py
logger = logging.getLogger("chat_monitor")

# WebSockets logger is too verbose, so keep it at WARNING level by default
ws_logger = logging.getLogger("websockets")
ws_logger.setLevel(logging.WARNING)

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

def save_chat(msgs, filepath):
    """Simple direct save of chat messages to file"""
    try:
        # Make sure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Write directly to the final file
        with open(filepath, "w", encoding="utf-8") as chat_file:
            chat_file.write(json.dumps(msgs, indent=4, ensure_ascii=False))
        
        logger.info(f"Saved {len(msgs)} messages to chat file: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Error saving chat data to {filepath}: {e}")
        logger.debug(traceback.format_exc())
        return False

def parti_chat(platform, username, path, stop_event=None):
    """
    Monitor Parti chat with immediate termination on stop signal
    
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
    
    # Define file path
    chat_file = os.path.join(path, "chat.json")
    
    # Save interval for backups
    last_save_time = time.time()
    save_interval = 30  # Save backup every 30 seconds
        
    try:
        with connect(PARTI_WS_URI, additional_headers=headers, open_timeout=10) as websocket:
            # Set a timeout so we can periodically check the stop_event
            websocket.timeout = 1.0  # 1 second timeout
            
            # Subscribe to the chat
            websocket.send(json.dumps({"subscribe_options":{"ChatPublic":{"user_id": user_id}}}))
            logger.info(f"Connected to chat for user {user_id}")
            
            # Process messages until told to stop
            while not stop_event.is_set():
                try:
                    msg = websocket.recv()
                    if logger.level <= logging.DEBUG:
                        logger.debug(f"Chat message received: {msg[:100]}...")  # Print first 100 chars in debug mode
                    
                    msgs.append(json.loads(msg))
                    
                    # Periodic backup save
                    current_time = time.time()
                    if current_time - last_save_time > save_interval:
                        save_chat(msgs, chat_file)
                        last_save_time = current_time
                        
                except TimeoutError:
                    # Check stop_event and exit immediately if set
                    if stop_event.is_set():
                        logger.info("Stop event detected, exiting immediately")
                        break
                    
                    # Just continue to next iteration
                    continue
                except Exception as e:
                    logger.error(f"Error in WebSocket connection: {e}")
                    logger.debug(traceback.format_exc())
                    break
    except Exception as e:
        logger.error(f"Error establishing WebSocket connection: {e}")
        logger.debug(traceback.format_exc())
    finally:
        # Save all collected messages to file on exit
        if msgs:
            save_chat(msgs, chat_file)
            logger.info(f"Saved {len(msgs)} chat messages on exit")
        else:
            logger.warning("Chat monitoring stopped, no messages collected")
    
    logger.info("Chat monitoring thread exiting")
    return msgs

if __name__ == "__main__":
    # When running directly as a script
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor Parti chat messages")
    parser.add_argument("platform", help="Platform name (e.g., 'parti')")
    parser.add_argument("username", help="Username to monitor")
    parser.add_argument("--output", "-o", default="./chat_output", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Configure logging for direct script execution
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(console)
        
        # Also enable websockets debug logging
        ws_logger.setLevel(logging.DEBUG)
        ws_console = logging.StreamHandler()
        ws_console.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        ws_logger.addHandler(ws_console)
    
    # Create output directory
    os.makedirs(args.output, exist_ok=True)
    
    print(f"Monitoring chat for {args.platform}/{args.username}, press Ctrl+C to stop")
    
    try:
        parti_chat(args.platform, args.username, args.output)
    except KeyboardInterrupt:
        print("\nChat monitoring stopped by user")
        sys.exit(0)