"""Generate icon.png and icon.ico (a friendly robot head) for the app."""
from PIL import Image, ImageDraw

SZ = 256
img = Image.new("RGBA", (SZ, SZ), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

BLUE = (47, 129, 247, 255)
BLUE_D = (26, 92, 200, 255)
DARK = (15, 20, 27, 255)
WHITE = (255, 255, 255, 255)

# antenna
d.line([(128, 54), (128, 30)], fill=BLUE_D, width=10)
d.ellipse([116, 16, 140, 40], fill=(210, 153, 9, 255))  # amber bulb

# head (rounded square)
d.rounded_rectangle([34, 52, 222, 224], radius=46, fill=BLUE, outline=BLUE_D, width=6)

# ears
d.rounded_rectangle([16, 112, 36, 164], radius=10, fill=BLUE_D)
d.rounded_rectangle([220, 112, 240, 164], radius=10, fill=BLUE_D)

# screen/face panel
d.rounded_rectangle([58, 84, 198, 196], radius=30, fill=DARK)

# eyes
for cx in (100, 156):
    d.ellipse([cx - 22, 112 - 22, cx + 22, 112 + 22], fill=WHITE)
    d.ellipse([cx - 9, 112 - 9, cx + 9, 112 + 9], fill=(47, 129, 247, 255))

# smile
d.rounded_rectangle([98, 156, 158, 172], radius=8, fill=WHITE)

img.save("icon.png")
img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                            (128, 128), (256, 256)])
print("wrote icon.png and icon.ico")
