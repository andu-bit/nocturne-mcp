"""
从酒馆角色卡 PNG 中提取 JSON 数据
用法: python extract_chara_card.py <角色卡.png> [输出路径.json]
"""

import sys
import base64
import json
from PIL import Image


def extract(png_path, out_path=None):
    img = Image.open(png_path)
    chara = img.text.get("chara")
    if not chara:
        print(f"[失败] {png_path} 中没有找到 chara 元数据")
        return

    data = json.loads(base64.b64decode(chara).decode("utf-8"))

    if out_path is None:
        out_path = png_path.rsplit(".", 1)[0] + "_extracted.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    name = data.get("data", data).get("name", data.get("name", "?"))
    print(f"[成功] {name} -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python extract_chara_card.py <角色卡.png> [输出.json]")
        sys.exit(1)

    png = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    extract(png, out)
