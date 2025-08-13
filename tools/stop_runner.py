# tools/stop_runner.py
# -*- coding: utf-8 -*-
import os, sys

FLAG = ".runner.lock/stop.flag"

def main():
    os.makedirs(os.path.dirname(FLAG), exist_ok=True)
    with open(FLAG, "w") as f:
        f.write("stop")
    print(f"✅ Đã tạo {FLAG}. Runner đọc thấy sẽ dừng an toàn ở tick kế tiếp.")

if __name__ == "__main__":
    main()