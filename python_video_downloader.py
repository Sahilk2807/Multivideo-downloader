from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import tempfile
import threading
import time
from urllib.parse import urlparse
import re

app = Flask(__name__)
CORS(app)

# Configuration
DOWNLOAD_PATH = tempfile.gettempdir()
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit

class VideoDownloader:
    def __init__(self):
        self.download_progress = {}
        
    def get_video_info(self, url):
        """Extract video information without downloading"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Unknown'),
                    'formats': self._extract_formats(info),
                    'platform': self._detect_platform(url)
                }
        except Exception as e:
            raise Exception(f"Failed to extract video info: {str(e)}")
    
    def _extract_formats(self, info):
        """Extract available formats from video info"""
        formats = []
        if 'formats' in info:
            for fmt in info['formats']:
                if fmt.get('vcodec') != 'none':  # Has video
                    formats.append({
                        'format_id': fmt.get('format_id'),
                        'quality': fmt.get('height', 'Unknown'),
                        'ext': fmt.get('ext', 'mp4'),
                        'filesize': fmt.get('filesize', 0)
                    })
        return formats
    
    def _detect_platform(self, url):
        """Detect platform from URL"""
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'instagram.com' in url:
            return 'instagram'
        elif 'tiktok.com' in url:
            return 'tiktok'
        else:
            return 'unknown'
    
    def download_video(self, url, format_type='video', quality='720p'):
        """Download video with specified quality and format"""
        try:
            # Generate unique filename
            timestamp = str(int(time.time()))
            
            if format_type == 'audio':
                output_path = os.path.join(DOWNLOAD_PATH, f'audio_{timestamp}.%(ext)s')
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': output_path,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'quiet': True,
                    'no_warnings': True,
                }
            else:
                output_path = os.path.join(DOWNLOAD_PATH, f'video_{timestamp}.%(ext)s')
                
                # Quality mapping
                quality_map = {
                    '144p': 'worst[height<=144]',
                    '240p': 'worst[height<=240]',
                    '360p': 'best[height<=360]',
                    '480p': 'best[height<=480]',
                    '720p': 'best[height<=720]',
                    '1080p': 'best[height<=1080]',
                    '1440p': 'best[height<=1440]',
                    '2160p': 'best[height<=2160]'
                }
                
                format_selector = quality_map.get(quality, 'best[height<=720]')
                
                ydl_opts = {
                    'format': f'{format_selector}/best',
                    'outtmpl': output_path,
                    'quiet': True,
                    'no_warnings': True,
                }
            
            # Add progress hook
            def progress_hook(d):
                if d['status'] == 'downloading':
                    self.download_progress[timestamp] = {
                        'status': 'downloading',
                        'percent': d.get('_percent_str', '0%'),
                        'speed': d.get('_speed_str', 'N/A')
                    }
                elif d['status'] == 'finished':
                    self.download_progress[timestamp] = {
                        'status': 'finished',
                        'filename': d['filename']
                    }
            
            ydl_opts['progress_hooks'] = [progress_hook]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            # Return the downloaded file info
            if timestamp in self.download_progress:
                return {
                    'success': True,
                    'download_id': timestamp,
                    'status': 'completed'
                }
            else:
                raise Exception("Download completed but file not found")
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

# Initialize downloader
downloader = VideoDownloader()

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Get video information endpoint"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        if not is_valid_url(url):
            return jsonify({'error': 'Invalid URL'}), 400
        
        info = downloader.get_video_info(url)
        return jsonify(info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    """Download video endpoint"""
    try:
        data = request.get_json()
        url = data.get('url')
        format_type = data.get('format', 'video')
        quality = data.get('quality', '720p')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        if not is_valid_url(url):
            return jsonify({'error': 'Invalid URL'}), 400
        
        # Start download in background thread
        def download_task():
            return downloader.download_video(url, format_type, quality)
        
        thread = threading.Thread(target=download_task)
        thread.start()
        
        # For demo, we'll return immediately
        # In production, you might want to implement proper async handling
        result = downloader.download_video(url, format_type, quality)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/progress/<download_id>', methods=['GET'])
def get_progress(download_id):
    """Get download progress"""
    if download_id in downloader.download_progress:
        return jsonify(downloader.download_progress[download_id])
    else:
        return jsonify({'error': 'Download not found'}), 404

@app.route('/api/download-file/<download_id>', methods=['GET'])
def download_file(download_id):
    """Serve downloaded file"""
    try:
        if download_id in downloader.download_progress:
            file_info = downloader.download_progress[download_id]
            if file_info['status'] == 'finished':
                filename = file_info['filename']
                if os.path.exists(filename):
                    return send_file(filename, as_attachment=True)
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/supported-sites', methods=['GET'])
def supported_sites():
    """Get list of supported sites"""
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            extractors = ydl.list_extractors()
            sites = []
            
            # Filter popular sites
            popular_sites = [
                'youtube', 'instagram', 'tiktok', 'twitter', 'facebook',
                'vimeo', 'dailymotion', 'twitch', 'reddit', 'pinterest'
            ]
            
            for extractor in extractors:
                extractor_name = extractor.lower()
                for site in popular_sites:
                    if site in extractor_name:
                        sites.append({
                            'name': site.title(),
                            'extractor': extractor
                        })
                        break
            
            return jsonify({'supported_sites': sites})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def is_valid_url(url):
    """Validate URL format and supported platforms"""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        
        # Check for supported platforms
        supported_domains = [
            'youtube.com', 'youtu.be', 'instagram.com', 'tiktok.com',
            'twitter.com', 'x.com', 'facebook.com', 'vimeo.com',
            'dailymotion.com', 'twitch.tv'
        ]
        
        return any(domain in parsed.netloc.lower() for domain in supported_domains)
        
    except Exception:
        return False

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'features': ['video_download', 'audio_extraction', 'multi_platform']
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({'error': 'File too large'}), 413

# Cleanup old files periodically
def cleanup_old_files():
    """Remove files older than 1 hour"""
    while True:
        try:
            current_time = time.time()
            for filename in os.listdir(DOWNLOAD_PATH):
                if filename.startswith(('video_', 'audio_')):
                    file_path = os.path.join(DOWNLOAD_PATH, filename)
                    if os.path.isfile(file_path):
                        file_age = current_time - os.path.getctime(file_path)
                        if file_age > 3600:  # 1 hour
                            os.remove(file_path)
                            print(f"Cleaned up old file: {filename}")
        except Exception as e:
            print(f"Cleanup error: {str(e)}")
        
        time.sleep(1800)  # Run every 30 minutes

if __name__ == '__main__':
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
    cleanup_thread.start()
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)

                