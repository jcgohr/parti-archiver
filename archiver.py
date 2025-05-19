from functions import split_parti_url
from video import download_with_callback
from chat import parti_chat
from api import isLive, getUserId
import threading
import datetime
import time
import sys
import os
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("parti_archiver.log")
    ]
)
logger = logging.getLogger("parti_archiver")

# Constants
DELAY = 15  # Seconds between checks for stream status
CHAT_SHUTDOWN_TIMEOUT = 60  # Allow up to 60 seconds for chat thread to shut down
MAX_OFFLINE_CHECKS = 3  # Number of consecutive offline checks before considering stream ended

def archive_stream(parti_url):
    """
    Archive a Parti.com stream (video and chat)
    
    Args:
        parti_url: URL to the Parti.com stream
    """
    platform, username = split_parti_url(parti_url)
    logger.info(f"Starting archiver for {platform}/{username}")
    
    offline_count = 0
    
    while True:
        try:
            user_id = getUserId(platform, username)
            is_streaming = isLive(user_id)
            
            if is_streaming:
                # Reset offline counter if we detect the stream
                offline_count = 0
                
                # Create directory for this stream session
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                stream_dir = f"{username}_{timestamp}/"
                os.makedirs(stream_dir, exist_ok=True)
                logger.info(f"Stream detected! Creating directory: {stream_dir}")
                
                # Events for thread coordination
                stop_event = threading.Event()  # Signals chat thread to stop
                download_complete = threading.Event()  # Signals when download is done
                download_success = threading.Event()  # Indicates if download was successful
                
                # Define callback for when download finishes
                def on_download_complete(success=True):
                    if success:
                        download_success.set()
                    
                    logger.info("Download completed, will stop chat collection soon...")
                    download_complete.set()
                    
                    # Give chat thread a few more seconds to collect final messages
                    time.sleep(5)
                    stop_event.set()
                    logger.info("Stop signal sent to chat thread")
                
                # Wrapper to pass success status from video download thread
                def download_thread_fn():
                    try:
                        success = download_with_callback(parti_url, stream_dir, 
                                         lambda: on_download_complete(True))
                        if not success:
                            logger.warning("Download reported failure")
                            on_download_complete(False)
                    except Exception as e:
                        logger.error(f"Unhandled exception in download thread: {e}")
                        logger.debug(traceback.format_exc())
                        on_download_complete(False)
                
                # Create and start threads for video download and chat collection
                dl_thread = threading.Thread(
                    target=download_thread_fn,
                    name="VideoDownload"
                )
                chat_thread = threading.Thread(
                    target=parti_chat, 
                    args=(platform, username, stream_dir, stop_event),
                    name="ChatCollection"
                )
                
                threads = [dl_thread, chat_thread]
                
                # Start each thread
                logger.info("Starting download and chat threads...")
                for t in threads:
                    t.start()
                
                try:
                    # Wait for download to complete (which will then signal chat to stop)
                    consecutive_offline = 0
                    while not download_complete.is_set():
                        time.sleep(1)
                        
                        # Check if download is still running
                        if not dl_thread.is_alive() and not download_complete.is_set():
                            logger.warning("Download thread ended without setting download_complete flag")
                            on_download_complete(False)
                        
                        # If stream goes offline, this might be a good time to stop
                        try:
                            if not isLive(user_id):
                                consecutive_offline += 1
                                if consecutive_offline >= MAX_OFFLINE_CHECKS:
                                    logger.info(f"Stream appears to have ended (offline for {consecutive_offline} checks), signaling stop...")
                                    if not download_complete.is_set():
                                        on_download_complete(True)  # Treat as success even if partial
                                    break
                            else:
                                consecutive_offline = 0  # Reset counter if stream is back online
                        except Exception as e:
                            logger.warning(f"Error checking live status: {e}")
                    
                    # Download is now complete, wait for chat thread to finish
                    logger.info(f"Waiting for chat collection to complete (timeout: {CHAT_SHUTDOWN_TIMEOUT}s)...")
                    chat_thread.join(timeout=CHAT_SHUTDOWN_TIMEOUT)
                    
                    if chat_thread.is_alive():
                        logger.warning("Chat thread did not terminate in time")
                        logger.info("Forcibly ending the current recording session...")
                        # We'll let the thread continue running but move on in the main loop
                    else:
                        logger.info("Chat collection completed successfully")
                        
                except KeyboardInterrupt:
                    logger.info("Interrupted by user, shutting down...")
                    stop_event.set()  # Signal threads to stop
                    
                    # Wait briefly for threads to terminate
                    for t in threads:
                        t.join(timeout=5)
                    
                    # Re-raise to exit the main loop
                    raise KeyboardInterrupt()
            else:
                # Streamer is not live
                offline_count += 1
                logger.info(f"Streamer not online (check {offline_count}), sleeping for {DELAY} seconds")
                time.sleep(DELAY)
                
        except KeyboardInterrupt:
            logger.info("Shutting down archiver...")
            break
        except Exception as e:
            logger.error(f"Error in main archiver loop: {e}")
            logger.debug(traceback.format_exc())
            time.sleep(DELAY)  # Sleep to avoid rapid error loops

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python archiver.py <parti_url>")
        sys.exit(1)
        
    parti_url = sys.argv[1]
    
    try:
        archive_stream(parti_url)
    except KeyboardInterrupt:
        print("\nArchiver shut down by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)