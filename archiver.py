from functions import split_parti_url
from video import download_with_callback
from chat import parti_chat
from api import isLive, getUserId
import threading
import datetime
import time
import sys
import os

DELAY = 15
CHAT_SHUTDOWN_TIMEOUT = 60  # Allow up to 60 seconds for chat thread to shut down

parti_url = sys.argv[1]
platform, username = split_parti_url(parti_url)

while True:
    if isLive(getUserId(platform, username)):
        stream_dir = f"{username}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}/"
        os.makedirs(stream_dir, exist_ok=True)
        print(f"Stream detected! Creating directory: {stream_dir}")
        
        # Create an event for signaling thread termination
        stop_event = threading.Event()
        download_complete = threading.Event()
        
        # Define callback for when download finishes
        def on_download_complete():
            print("Download completed, will stop chat collection soon...")
            download_complete.set()
            # Give chat thread a few more seconds to collect final messages
            time.sleep(5)
            stop_event.set()
            print("Stop signal sent to chat thread")
        
        # My idea is to have a video and chat download thread, this is probably the best way to handle both functions from one script
        dl_thread = threading.Thread(
            target=download_with_callback, 
            args=(parti_url, stream_dir, on_download_complete)
        )
        chat_thread = threading.Thread(
            target=parti_chat, 
            args=(platform, username, stream_dir, stop_event)
        )

        threads = [dl_thread, chat_thread]

        # Start each thread
        print("Starting download and chat threads...")
        for t in threads:
            t.start()

        try:
            # Wait for download to complete (which will then signal chat to stop)
            while not download_complete.is_set():
                time.sleep(1)
                # Check if download is still running
                if not dl_thread.is_alive() and not download_complete.is_set():
                    print("Download thread ended without setting download_complete flag")
                    on_download_complete()
                
                # If stream goes offline, this might be a good time to stop
                if not isLive(getUserId(platform, username)):
                    print("Stream appears to have ended, signaling stop...")
                    stop_event.set()
                    break
            
            # Wait for chat thread to finish (should now exit gracefully)
            print(f"Waiting for chat collection to complete (timeout: {CHAT_SHUTDOWN_TIMEOUT}s)...")
            chat_thread.join(timeout=CHAT_SHUTDOWN_TIMEOUT)
            
            if chat_thread.is_alive():
                print("Warning: Chat thread did not terminate in time")
                print("Forcibly ending the current recording session...")
                # We'll let the thread continue running but move on in the main loop
                # Next iteration will create a new directory if the stream is still live
            else:
                print("Chat collection completed successfully")
                
        except KeyboardInterrupt:
            print("Interrupted by user, shutting down...")
            stop_event.set()  # Signal threads to stop
            
            # Wait briefly for threads to terminate
            for t in threads:
                t.join(timeout=5)
                
    # Scan for live status every few seconds
    print(f"Streamer not online, sleeping for {DELAY} seconds")
    time.sleep(DELAY)