"""
生成圆形多尺寸 ICO 图标
将 icon.png 裁剪为圆形并生成 whale.ico（含 256/128/64/48/32/16 多尺寸）
"""
from PIL import Image, ImageDraw
import struct, io, os

def create_circular_icon(input_file, output_file):
    # 打开原始 PNG（RGBA）
    img = Image.open(input_file).convert('RGBA')
    w, h = img.size

    # 1. 找到内容边界（非透明区域）
    min_x, min_y = w, h
    max_x, max_y = 0, 0
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y))[3] > 0:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    print(f"内容区域: ({min_x},{min_y}) -> ({max_x},{max_y})")

    # 2. 裁剪内容区域
    content = img.crop((min_x, min_y, max_x + 1, max_y + 1))
    cw, ch = content.size
    print(f"裁剪后尺寸: {cw}x{ch}")

    # 3. 创建正方形画布（加 5% 内边距）
    size = max(cw, ch)
    pad = int(size * 0.05)
    square_size = size + pad * 2
    square = Image.new('RGBA', (square_size, square_size), (0, 0, 0, 0))
    square.paste(content, ((square_size - cw) // 2, (square_size - ch) // 2))

    # 4. 创建圆形蒙版
    mask = Image.new('L', (square_size, square_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, square_size, square_size], fill=255)

    # 5. 应用圆形蒙版
    result = Image.new('RGBA', (square_size, square_size), (0, 0, 0, 0))
    result.paste(square, (0, 0), mask)

    # 6. 生成多尺寸 PNG 数据
    sizes = [256, 128, 64, 48, 32, 16]
    png_data_list = []
    for s in sizes:
        resized = result.resize((s, s), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format='PNG')
        png_data_list.append(buf.getvalue())

    # 7. 手动构建 ICO 文件
    count = len(sizes)
    ico_header = struct.pack('<HHH', 0, 1, count)
    ico_data = bytearray(ico_header)

    offset = 6 + count * 16
    for s, png_data in zip(sizes, png_data_list):
        w_entry = 0 if s == 256 else s
        h_entry = 0 if s == 256 else s
        entry = struct.pack('<BBBBHHII', w_entry, h_entry, 0, 0, 1, 32, len(png_data), offset)
        ico_data.extend(entry)
        offset += len(png_data)

    for png_data in png_data_list:
        ico_data.extend(png_data)

    # 8. 写入文件
    with open(output_file, 'wb') as f:
        f.write(ico_data)

    fsize = os.path.getsize(output_file)
    print(f"✅ {output_file} 已生成（圆形多尺寸图标）")
    print(f"   文件大小: {fsize} bytes ({fsize/1024:.1f} KB)")
    print(f"   包含尺寸: {sizes}")
    return True

if __name__ == '__main__':
    project_dir = os.path.dirname(os.path.abspath(__file__))
    create_circular_icon(
        os.path.join(project_dir, 'icon.png'),
        os.path.join(project_dir, 'whale.ico')
    )
