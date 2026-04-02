import os
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import time
from flask_cors import CORS
from flask_compress import Compress
from moviepy.editor import VideoFileClip
import utils_audio
import utils_video
import utils_cache

app = Flask(__name__)
CORS(app)
Compress(app)  # Enable gzip compression for all responses
import concurrent.futures

def process_audio_task(audio_path):
    """Wrapper to handle audio analysis safely"""
    if os.path.exists(audio_path):
        return utils_audio.analyze_audio_file(audio_path)
    return {
        "transcript": "",
        "speaking_speed": {"wpm": 0, "level": "N/A"},
        "speed_chart": [],
        "filler_words": {"percentage": 0, "total_count": 0, "breakdown": {}}
    }

@app.route("/analyze", methods=["POST"])
def analyze_video():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files["file"]
    
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size == 0:
        return jsonify({"error": "File is empty"}), 400

    
    # Ensure uploads directory exists
    if not os.path.exists("uploads"):
        os.makedirs("uploads")

    # Save with unique filename in uploads folder
    filename = secure_filename(file.filename)
    video_path = os.path.join("uploads", f"{int(time.time())}_{filename}")
    file.save(video_path)

    try:
        # Generate hash for caching
        video_hash = utils_cache.get_file_hash(video_path)
        print(f"📹 Video hash: {video_hash[:8]}...")
        
        # Check cache first
        cached_result = utils_cache.get_cached_result(video_hash)
        if cached_result:
            print("⚡ Cache hit! Returning cached results...")
            return jsonify(cached_result)
        
        print("🔄 Cache miss. Processing video...")
        
        # Cleanup previous audio file
        if os.path.exists("audio.wav"):
            os.remove("audio.wav")

        # Extract audio using direct FFmpeg subprocess (Low Memory Approach)
        import subprocess
        import imageio
        
        audio_path = "audio.wav"
        
        try:
            print("🔊 Extracting audio using FFmpeg...")
            ffmpeg_exe = imageio.plugins.ffmpeg.get_exe()
            
            # Command: ffmpeg -i video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav -y
            # -vn: No video
            # -acodec pcm_s16le: WAV format
            # -ar 16000: 16k sample rate (optimal for Whisper)
            # -ac 1: Mono audio
            # -y: Overwrite output
            
            command = [
                ffmpeg_exe, 
                "-i", video_path, 
                "-vn", 
                "-acodec", "pcm_s16le", 
                "-ar", "16000", 
                "-ac", "1", 
                audio_path, 
                "-y"
            ]
            
            # Run silently
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("✅ Audio extracted successfully")
            
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg failed: {e}")
            return jsonify({"error": "Failed to extract audio from video"}), 400
        except Exception as e:
            print(f"Audio extraction error: {e}")
            return jsonify({"error": f"Invalid video file: {str(e)}"}), 400

        # Run Audio and Video analysis acting in PARALLEL to save time
        print("🚀 Starting PARALLEL analysis...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit tasks
            future_audio = executor.submit(process_audio_task, audio_path)
            
            # Optimize video parameters
            stride, max_frames = utils_cache.optimize_video_params(video_path)
            print(f"⚙️ Video params: stride={stride}, max_frames={max_frames}")
            
            future_video = executor.submit(utils_video.analyze_video, video_path, stride, max_frames)
            
            # Wait for results
            audio_results = future_audio.result()
            video_results = future_video.result()
            
        print("✅ Parallel analysis complete!")
        
        # Generate professional feedback
        feedback = generate_professional_feedback(audio_results, video_results)
        
        # Construct response with all new features
        # Normalize speaking speed chart values properly
        rms_values = [chunk["rms"] for chunk in audio_results["speed_chart"]]
        max_rms = max(rms_values) if rms_values else 1
        normalized_values = [round((rms / max_rms) * 100, 2) for rms in rms_values] if max_rms > 0 else []
        
        response = {
            "transcript": audio_results["transcript"],
            "sentiment": "Neutral",
            "speaking_speed": {
                "average": audio_results["speaking_speed"]["wpm"],
                "level": audio_results["speaking_speed"]["level"],
                "timestamps": [chunk["time_sec"] for chunk in audio_results["speed_chart"]],
                "values": normalized_values
            },
            "filler_words": {
                **audio_results["filler_words"],
                "top_filler_words": audio_results["filler_words"]["breakdown"]  # Map for frontend
            },
            "posture": {
                "score": video_results["posture"]["score"],
                "label": video_results["posture"]["label"],
                "ratio": video_results["posture"]["ratio"]
            },
            "gestures": {
                "total_movements": video_results["gestures"]["total_movements"],
                "avg_intensity": video_results["gestures"]["avg_intensity"],
                "level": video_results["gestures"]["level"],
                "heatmap": video_results["gestures"]["heatmap"]
            },
            "eye_contact": {
                "percentage": video_results["eye_contact"]["percentage"],
                "level": video_results["eye_contact"]["level"],
                "ratio": video_results["eye_contact"]["ratio"]
            },
            "confidence_index": video_results["confidence_index"],
            "professional_feedback": feedback
        }
        
        # Save to cache for future requests
        utils_cache.save_to_cache(video_hash, response)
        
        # Periodically clean old cache (every 10th request approximately)
        import random
        if random.randint(1, 10) == 1:
            utils_cache.clear_old_cache(max_age_days=7)
        
        return jsonify(response)

    except Exception as e:
        print(f"Error processing video: {e}")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500
    
    finally:
        # Cleanup: Delete temporary audio file (keeping video in uploads/)
        try:
            if os.path.exists("audio.wav"):
                os.remove("audio.wav")
        except Exception as cleanup_error:
            print(f"Warning: Failed to cleanup files: {cleanup_error}")


def generate_professional_feedback(audio_results, video_results):
    """Generate comprehensive professional feedback"""
    feedback = []
    
    # Speaking speed feedback with updated thresholds
    wpm = audio_results["speaking_speed"]["wpm"]
    if wpm < 80:
        feedback.append("🎯 **Speaking Speed**: Your pace is very slow. Try to speak faster to maintain audience engagement and energy.")
    elif wpm < 110:
        feedback.append("🎯 **Speaking Speed**: Your pace is a bit slow. Consider speaking slightly faster to keep your audience engaged.")
    elif wpm <= 160:
        feedback.append("✅ **Speaking Speed**: Excellent pace! You're speaking at an ideal rate (120-160 WPM) for comprehension and engagement.")
    elif wpm <= 180:
        feedback.append("🎯 **Speaking Speed**: You're speaking quite fast. Slow down slightly to ensure clarity and give your audience time to absorb information.")
    else:
        feedback.append("⚠️ **Speaking Speed**: You're speaking very fast. Significantly slow down to improve clarity and comprehension.")
    
    # Filler words feedback
    filler_pct = audio_results["filler_words"]["percentage"]
    if filler_pct > 5:
        feedback.append(f"⚠️ **Filler Words**: You used filler words {filler_pct}% of the time. Practice pausing instead of using 'um', 'uh', or 'like'.")
    elif filler_pct > 2:
        feedback.append(f"🎯 **Filler Words**: Moderate use of filler words ({filler_pct}%). Work on reducing these for more polished delivery.")
    else:
        feedback.append(f"✅ **Filler Words**: Great job! Minimal filler words ({filler_pct}%).")
    
    # Posture feedback
    posture_label = video_results["posture"]["label"]
    if posture_label == "excellent" or posture_label == "good":
        feedback.append(f"✅ **Posture**: {posture_label.capitalize()} posture maintained throughout. You project confidence!")
    else:
        feedback.append(f"🎯 **Posture**: Your posture needs improvement. Stand straight with shoulders back to appear more confident.")
    
    # Gesture feedback
    gesture_level = video_results["gestures"]["level"]
    if gesture_level == "balanced":
        feedback.append("✅ **Gestures**: Perfect balance of hand movements. Natural and engaging!")
    elif gesture_level == "low":
        feedback.append("🎯 **Gestures**: Use more hand gestures to emphasize key points and appear more dynamic.")
    else:
        feedback.append("⚠️ **Gestures**: Too many hand movements can be distracting. Be more intentional with gestures.")
    
    # Eye contact feedback
    eye_pct = video_results["eye_contact"]["percentage"]
    if eye_pct > 70:
        feedback.append(f"✅ **Eye Contact**: Excellent eye contact ({eye_pct}%)! You're connecting well with your audience.")
    elif eye_pct > 40:
        feedback.append(f"🎯 **Eye Contact**: Good effort ({eye_pct}%), but try to maintain eye contact more consistently.")
    else:
        feedback.append(f"⚠️ **Eye Contact**: Low eye contact ({eye_pct}%). Look at your audience more to build trust and engagement.")
    
    # Overall confidence
    confidence = video_results["confidence_index"]
    if confidence >= 75:
        feedback.append(f"🌟 **Overall**: Outstanding performance! Confidence Index: {confidence}/100. You're a natural speaker!")
    elif confidence >= 60:
        feedback.append(f"👍 **Overall**: Good performance! Confidence Index: {confidence}/100. Keep practicing to reach excellence.")
    else:
        feedback.append(f"💪 **Overall**: Confidence Index: {confidence}/100. Focus on the areas above to improve your presence.")
    
    return "\n\n".join(feedback)

if __name__ == "__main__":
    # Disable reloader to save memory (prevents spawning two processes)
    app.run(debug=True, use_reloader=False)
