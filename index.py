import subprocess
import time

while True:
    try:
        process = subprocess.Popen(["python", "tanlovbot.py"])  # Dastur nomini o'zgartiring
        process.wait()
    except Exception as e:
        print(f"Xatolik yuz berdi: {e}")
    print("Dastur qayta ishga tushirilyapti...")
    time.sleep(5)  # 5 sekund kutish