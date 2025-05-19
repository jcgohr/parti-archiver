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
import argparse

# Configure root logger first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parti_archiver.log")  # Always log to file
    ]
)

# Get logger for this module
logger = logging.getLogger("parti_archiver")

# Constants
DELAY = 120  # Seconds between checks for stream status
CHAT_SHUTDOWN_TIMEOUT = 20  # Reduced from 60s to 20s since we've improved chat shutdown
MAX_OFFLINE_CHECKS = 3  # Number of consecutive offline checks before considering stream ended

def setup_logging(verbose):
    """Configure logging based on verbosity level"""
    # Root logger already set up with file handler
    
    # Define a console handler with appropriate level
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    if verbose:
        # In verbose mode, show all INFO level and above
        console_handler.setLevel(logging.INFO)
        # Also set DEBUG level for certain loggers
        logging.getLogger("video_downloader").setLevel(logging.DEBUG)
        logging.getLogger("chat_monitor").setLevel(logging.DEBUG)
    else:
        # In non-verbose mode, only show CRITICAL messages on the console
        # This effectively silences most output while still logging to file
        console_handler.setLevel(logging.CRITICAL)
        
        # Set specific levels for component loggers
        logging.getLogger("video_downloader").setLevel(logging.INFO)
        logging.getLogger("chat_monitor").setLevel(logging.INFO)
    
    # Add console handler to root logger
    logging.getLogger().addHandler(console_handler)
    
    # Set parti_archiver logger level (our main module)
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

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
                print(f"Stream detected! Creating directory: {stream_dir}")  # Always show this
                logger.info(f"Stream detected! Creating directory: {stream_dir}")
                
                # Events for thread coordination
                stop_event = threading.Event()  # Signals chat thread to stop
                download_complete = threading.Event()  # Signals when download is done
                download_success = threading.Event()  # Indicates if download was successful
                
                # Define callback for when download finishes
                def on_download_complete(success=True):
                    if success:
                        download_success.set()
                    
                    logger.info("Download completed, starting post-download wait period...")
                    download_complete.set()
                    
                    # Don't stop chat immediately - we'll wait in the main thread
                
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
                print(f"Starting download for {username}...")  # Always show this
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
                    
                    # After wait period, signal the chat thread to stop
                    logger.info("Post-download wait period complete, will stop chat collection")
                    stop_event.set()
                    logger.info("Stop signal sent to chat thread")
                    
                    # Download is now complete, wait for chat thread to finish
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
                    
                    print(f"Download completed: {stream_dir}")  # Always show this
                        
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
            print(f"Error: {e}")  # Always show errors
            logger.error(f"Error in main archiver loop: {e}")
            logger.debug(traceback.format_exc())
            time.sleep(DELAY)  # Sleep to avoid rapid error loops

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Archive Parti.com livestreams (video and chat)")
    
    parser.add_argument("url", 
                        help="URL of the Parti creator to monitor (e.g., https://parti.com/creator/parti/username)")
    
    parser.add_argument("-v", "--verbose", 
                        action="store_true", 
                        help="Enable verbose output with detailed logs")
    
    return parser.parse_args()

if __name__ == "__main__":
    # Parse command line arguments
    args = parse_args()
    
    # Set up logging based on verbosity
    setup_logging(args.verbose)
    
    # Display minimal startup info
    print(f"Parti Archiver started for: {args.url}")
    if not args.verbose:
        print("Run with -v or --verbose for detailed output")
    
    try:
        archive_stream(args.url)
    except KeyboardInterrupt:
        print("\nArchiver shut down by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        logger.critical(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())
        sys.exit(1)