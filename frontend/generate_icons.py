"""生成 PWA 图标（纯标准库，无需 Pillow）。
绘制：紫罗兰渐变底 + 居中白色对话气泡 + 三个点，满足 maskable 全幅要求。
"""
import struct, zlib, math, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

def make_icon(size):
    # RGBA 缓冲
    buf = bytearray([0]) * (size * size * 4)
    top = (109, 93, 252)   # #6d5dfc
    bot = (139, 124, 246)  # #8b7cf6
    cx, cy = size / 2, size / 2
    # 气泡：居中圆角矩形
    bw = size * 0.52
    bh = size * 0.42
    bx0, bx1 = cx - bw / 2, cx + bw / 2
    by0, by1 = cy - bh / 2 - size * 0.02, cy + bh / 2 - size * 0.02
    r = size * 0.16  # 圆角半径

    def in_bubble(x, y):
        # 圆角矩形判定
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            return False
        # 四个角的圆角
        for (ex, ey) in [(bx0 + r, by0 + r), (bx1 - r, by0 + r), (bx0 + r, by1 - r), (bx1 - r, by1 - r)]:
            pass
        # 简化为：内部矩形 + 角落圆角
        if x < bx0 + r and y < by0 + r:
            return (x - (bx0 + r)) ** 2 + (y - (by0 + r)) ** 2 <= r * r
        if x > bx1 - r and y < by0 + r:
            return (x - (bx1 - r)) ** 2 + (y - (by0 + r)) ** 2 <= r * r
        if x < bx0 + r and y > by1 - r:
            return (x - (bx0 + r)) ** 2 + (y - (by1 - r)) ** 2 <= r * r
        if x > bx1 - r and y > by1 - r:
            return (x - (bx1 - r)) ** 2 + (y - (by1 - r)) ** 2 <= r * r
        return True

    # 气泡下方的「小尾巴」三角
    def in_tail(x, y):
        tx0 = cx - size * 0.02 - size * 0.06
        tx1 = cx - size * 0.02 + size * 0.06
        ty0 = by1 - size * 0.01
        ty1 = by1 + size * 0.12
        if not (tx0 <= x <= tx1 and ty0 <= y <= ty1):
            return False
        # 三角：左上为尖
        return (x - tx0) >= (ty1 - y) * (tx1 - tx0) / (ty1 - ty0)

    for y in range(size):
        t = y / (size - 1)
        R = int(top[0] + (bot[0] - top[0]) * t)
        G = int(top[1] + (bot[1] - top[1]) * t)
        B = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(size):
            i = (y * size + x) * 4
            if in_bubble(x, y) or in_tail(x, y):
                buf[i] = 255
                buf[i + 1] = 255
                buf[i + 2] = 255
                buf[i + 3] = 255
            else:
                buf[i] = R
                buf[i + 1] = G
                buf[i + 2] = B
                buf[i + 3] = 255

    # 三个点
    dot_y = cy - size * 0.02
    dot_r = size * 0.045
    for k in (-0.16, 0.0, 0.16):
        dxc = cx + k * size
        for y in range(size):
            for x in range(size):
                if (x - dxc) ** 2 + (y - dot_y) ** 2 <= dot_r * dot_r:
                    i = (y * size + x) * 4
                    buf[i] = 109
                    buf[i + 1] = 93
                    buf[i + 2] = 252
                    buf[i + 3] = 255

    # 编码 PNG
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0
        raw.extend(buf[y * size * 4:(y + 1) * size * 4])

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
        return c

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return png

os.makedirs(OUT, exist_ok=True)
for s in (192, 512):
    with open(os.path.join(OUT, f"icon-{s}.png"), "wb") as f:
        f.write(make_icon(s))
    print("written icon-%d.png" % s)
