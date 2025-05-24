import yt_dlp
import os
import time
import logging
import traceback

# Configure logging - actual level will be set by archiver.py
logger = logging.getLogger("video_downloader")

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

class DownloadError(Exception):
    """Custom exception for download failures"""
    pass

def setup_yt_dlp_options(path, retry_on_error=True):
    """
    Configure yt-dlp options for live stream download
    
    Args:
        path: Directory to save the video
        retry_on_error: Whether to retry on transient errors
    """
    options = {
        "paths": {"home": path},
        "verbose": False,  # Keep yt-dlp quiet by default
        "format": "best",  # Use best quality available
        "outtmpl": "%(title)s.%(ext)s",
        "nocheckcertificate": True,
        "ignoreerrors": True,  # Skip unavailable videos in a playlist
        "no_warnings": True,
        "geo_bypass": True,
        "quiet": True,
        "no_color": False,
        "progress_hooks": [],  # Will be set in the download function
    }
    
    # Settings for handling live streams
    if retry_on_error:
        options.update({
            "retries": 10,  # Retry 10 times if download fails
            "fragment_retries": 10,  # Retry 10 times if a fragment fails
            "skip_unavailable_fragments": True,  # Skip unavailable fragments
            "keepvideo": True,  # Keep partial downloads
        })
    
    return options

def download_with_callback(link: str, path: str, completion_callback=None, retries=MAX_RETRIES):
    """
    Download video with graceful error handling and a callback when completed
    
    Args:
        link: The URL to download
        path: Directory to save the video
        completion_callback: Function to call when download completes (even on error)
        retries: Number of times to retry on failure
    
    Returns:
        bool: True if download was successful, False otherwise
    """
    # Ensure directory exists
    os.makedirs(path, exist_ok=True)
    
    # Track if any file was saved
    download_success = False
    attempted_retries = 0
    last_error = None
    
    while attempted_retries <= retries and not download_success:
        # If this is a retry, log and wait
        if attempted_retries > 0:
            logger.warning(f"Retry attempt {attempted_retries}/{retries} after error: {last_error}")
            time.sleep(RETRY_DELAY * attempted_retries)  # Increasing delay on each retry
        
        # Progress callback to monitor download
        file_size = 0
        downloaded_bytes = 0
        download_started = False
        download_finished = False
        
        def progress_hook(d):
            nonlocal file_size, downloaded_bytes, download_started, download_finished
            
            if d['status'] == 'downloading':
                download_started = True
                downloaded_bytes = d.get('downloaded_bytes', 0)
                if not file_size and 'total_bytes' in d:
                    file_size = d.get('total_bytes', 0)
                elif not file_size and 'total_bytes_estimate' in d:
                    file_size = d.get('total_bytes_estimate', 0)
                
                # Log progress at 10% intervals
                if file_size > 0:
                    progress = downloaded_bytes / file_size * 100
                    if progress % 10 < 1:  # Log roughly every 10%
                        logger.info(f"Download progress: {progress:.1f}% ({downloaded_bytes/(1024*1024):.1f} MB)")
            
            elif d['status'] == 'finished':
                download_finished = True
                logger.info(f"Download finished. Converting/Processing file...")
            
            elif d['status'] == 'error':
                logger.error(f"Download error: {d.get('error')}")
        
        try:
            # Configure options with the progress hook
            options = setup_yt_dlp_options(path)
            options['progress_hooks'] = [progress_hook]
            # No special handling for 404 errors here, let normal error handling work
            
            # Check log level to adjust yt-dlp verbosity
            if logger.level <= logging.DEBUG:
                options['verbose'] = True
                options['quiet'] = False
                options['no_warnings'] = False
            
            # Create a YouTube DL instance
            dl = yt_dlp.YoutubeDL(options)
            
            # Attempt to extract info first to validate the URL
            try:
                logger.info(f"Extracting info from {link}")
                info = dl.extract_info(link, download=False)
                if info is None:
                    logger.error("Could not extract info from URL")
                    raise DownloadError("Could not extract info from URL")
            except Exception as e:
                logger.error(f"Error extracting info: {e}")
                # Log but don't do special handling for 404 errors
                logger.error(f"Error extracting info: {e}")
                raise DownloadError(f"Invalid URL or content unavailable: {e}")
            
            # Now proceed with the download
            logger.info(f"Starting download from {link} to {path}")
            try:
                result = dl.download([link])
                
                # Check for successful download
                if result == 0 and (download_finished or downloaded_bytes > 0):
                    logger.info(f"Download completed successfully to {path}")
                    download_success = True
                else:
                    logger.warning(f"Download may have issues. yt-dlp return code: {result}")
                    
                    # If we got some data but yt-dlp reported an error, still consider it successful
                    # This helps with partial downloads of streams that end during recording
                    if downloaded_bytes > 0:
                        logger.info(f"Partial download saved ({downloaded_bytes/(1024*1024):.1f} MB)")
                        download_success = True
                    else:
                        raise DownloadError(f"Download failed with code {result}")
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"yt-dlp download error: {e}")
                raise
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"Download error: {e}")
            logger.debug(traceback.format_exc())
            attempted_retries += 1
            download_success = False
    
    # Final status report
    if download_success:
        logger.info(f"Download process completed with success={download_success}")
    else:
        logger.error(f"Download failed after {attempted_retries} retries. Last error: {last_error}")
    
    try:
        # Always call the callback if provided, regardless of success/failure
        if completion_callback:
            logger.info("Executing completion callback")
            completion_callback()
    except Exception as callback_error:
        logger.error(f"Error in completion callback: {callback_error}")
    
    return download_success

# Maintain backward compatibility with the original function
def download(link: str, path: str):
    """Legacy function for backward compatibility"""
    return download_with_callback(link, path)

if __name__ == "__main__":
    # Test the download function when this file is run directly
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Download video from URL")
    parser.add_argument("url", help="URL to download")
    parser.add_argument("--output", "-o", default="./download_test", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Configure console logger for direct script execution
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(console)
    
    print(f"Downloading {args.url} to {args.output}")
    result = download(args.url, args.output)
    print(f"Download {'succeeded' if result else 'failed'}")