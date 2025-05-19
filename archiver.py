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
CHAT_SHUTDOWN_TIMEOUT = 20  # Reduced from 60s to 20s since we've improved chat shutdown
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
                    
                    # Send stop signal immediately
                    # (The chat module now has its own grace period logic)
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
                    name="VideoDownload",
                    daemon=True  # Mark as daemon so it doesn't prevent program exit
                )
                chat_thread = threading.Thread(
                    target=parti_chat, 
                    args=(platform, username, stream_dir, stop_event),
                    name="ChatCollection",
                    daemon=True  # Mark as daemon so it doesn't prevent program exit
                )
                
                threads = [dl_thread, chat_thread]
                
                # Start each thread
                logger.info("Starting download and chat threads...")
                for t in threads:
                    t.start()
                
                try:
                    # Wait for download to complete (which will then signal chat to stop)
                    consecutive_offline = 0
                    download_check_interval = 1  # Check download status every 1 second
                    
                    while not download_complete.is_set():
                        time.sleep(download_check_interval)
                        
                        # Periodically check if threads are still alive
                        if not dl_thread.is_alive() and not download_complete.is_set():
                            logger.warning("Download thread ended without setting download_complete flag")
                            on_download_complete(False)
                            break
                        
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
                    # First, verify stop_event is set (just in case)
                    if not stop_event.is_set():
                        logger.warning("Stop event not set after download completion! Setting it now.")
                        stop_event.set()
                    
                    logger.info(f"Waiting for chat collection to complete (timeout: {CHAT_SHUTDOWN_TIMEOUT}s)...")
                    
                    # Use a polling approach rather than join() to improve responsiveness
                    chat_start_wait = time.time()
                    while chat_thread.is_alive() and (time.time() - chat_start_wait) < CHAT_SHUTDOWN_TIMEOUT:
                        time.sleep(0.5)  # Check every half second
                    
                    # Check final status
                    if chat_thread.is_alive():
                        logger.warning("Chat thread did not terminate in time. Thread will be abandoned.")
                        
                        # Check if the chat json file exists - if not, we might want to wait a bit longer
                        # as the thread could be in the process of saving
                        final_chat_file = os.path.join(stream_dir, "chat.json")
                        if not os.path.exists(final_chat_file):
                            logger.info("No final chat file detected, waiting an additional 5 seconds...")
                            time.sleep(5)
                        
                        # Note: Since we've set the thread as daemon, it won't prevent program exit
                        logger.info("Forcibly ending the current recording session...")
                    else:
                        logger.info("Chat collection completed successfully")
                        
                except KeyboardInterrupt:
                    logger.info("Interrupted by user, shutting down...")
                    stop_event.set()  # Signal threads to stop
                    
                    # No need to wait for threads since they're daemons
                    logger.info("Shutting down immediately. Daemon threads will be terminated.")
                    
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