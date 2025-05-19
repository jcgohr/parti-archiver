import yt_dlp

def download_with_callback(link: str, path: str, completion_callback=None):
    """
    Download video with a callback when completed
    
    Args:
        link: The URL to download
        path: Directory to save the video
        completion_callback: Function to call when download completes
    """
    try:
        dl = yt_dlp.YoutubeDL({
            "paths": {"home": path},
            "verbose": True,
        })
        dl.download(link)
        print(f"Download completed to {path}")
    except Exception as e:
        print(f"Download error: {e}")
    finally:
        # Always call the callback if provided
        if completion_callback:
            completion_callback()

# Maintain backward compatibility with the original function
def download(link: str, path: str):
    return download_with_callback(link, path)