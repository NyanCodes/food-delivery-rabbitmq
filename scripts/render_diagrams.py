"""Render presentation-friendly PNGs matching the Mermaid source diagrams."""

from pathlib import Path
from math import hypot

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "diagrams"
W, H = 1600, 900
NAVY, BLUE, ORANGE = "#17324D", "#DCEEFF", "#C8460A"
PALE, INK, MUTED, RED = "#F4F6F8", "#17191F", "#5F6670", "#B42318"


def font(size=28, bold=False):
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def canvas(title, subtitle):
    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 45), title, font=font(42, True), fill=INK)
    draw.text((70, 102), subtitle, font=font(22), fill=MUTED)
    return image, draw


def box(draw, xy, label, fill=PALE, outline="#CCD3DA", size=25):
    draw.rounded_rectangle(xy, radius=16, fill=fill, outline=outline, width=3)
    x1, y1, x2, y2 = xy
    lines = label.split("\n")
    heights = [draw.textbbox((0, 0), line, font=font(size, True))[3] for line in lines]
    y = (y1 + y2 - sum(heights) - 8 * (len(lines) - 1)) / 2
    for line, height in zip(lines, heights):
        width = draw.textbbox((0, 0), line, font=font(size, True))[2]
        draw.text(((x1 + x2 - width) / 2, y), line, font=font(size, True), fill=INK)
        y += height + 8


def arrow(draw, start, end, label=None, color=NAVY, dashed=False):
    if dashed:
        x1, y1 = start; x2, y2 = end
        for i in range(0, 20, 2):
            a, b = i / 20, min(1, (i + 1) / 20)
            draw.line((x1+(x2-x1)*a, y1+(y2-y1)*a,
                       x1+(x2-x1)*b, y1+(y2-y1)*b), fill=color, width=4)
    else:
        draw.line((*start, *end), fill=color, width=4)
    x1, y1 = start; x2, y2 = end
    length = hypot(x2-x1, y2-y1) or 1
    ux, uy = (x2-x1)/length, (y2-y1)/length
    px, py = -uy, ux
    draw.polygon([(x2, y2),
                  (x2-ux*16+px*9, y2-uy*16+py*9),
                  (x2-ux*16-px*9, y2-uy*16-py*9)], fill=color)
    if label:
        mx, my = (start[0]+end[0])/2, (start[1]+end[1])/2
        draw.text((mx-45, my-30), label, font=font(18), fill=color)


def save(image, name):
    image.save(OUT / name, optimize=True)


def architecture():
    image, d = canvas("RabbitMQ order architecture", "One event fans out to independent work queues; failures have a separate path.")
    box(d, (60, 330, 300, 465), "Customer\nand demo UI", BLUE)
    box(d, (370, 330, 610, 465), "FastAPI\nproducer", "#FFF0E8", ORANGE)
    box(d, (690, 310, 960, 485), "orders\ntopic exchange", BLUE, NAVY)
    queues = [(1040, 190, 1290, 300, "payment.process"),
              (1040, 365, 1290, 475, "restaurant.notify"),
              (1040, 540, 1290, 650, "notification.send")]
    workers = ["Payment worker", "Restaurant worker", "Notification worker"]
    arrow(d, (300, 398), (370, 398), "POST")
    arrow(d, (610, 398), (690, 398), "created")
    for index, (x1, y1, x2, y2, label) in enumerate(queues):
        box(d, (x1, y1, x2, y2), label, PALE, size=21)
        box(d, (1360, y1, 1570, y2), workers[index], "#E8F5E9", size=20)
        arrow(d, (960, 398), (1040, (y1+y2)//2))
        arrow(d, (1290, (y1+y2)//2), (1360, (y1+y2)//2))
    box(d, (690, 690, 960, 810), "PostgreSQL\nstate + timeline", "#F2EAFE", size=22)
    arrow(d, (825, 485), (825, 690), "events")
    box(d, (1040, 710, 1290, 810), "orders.dlq", "#FDECEC", RED, 21)
    arrow(d, (1170, 650), (1170, 710), "failed", RED, True)
    save(image, "architecture.png")


def before_after():
    image, d = canvas("Before and after RabbitMQ", "The work is similar; the customer's waiting time is not.")
    d.text((70, 185), "SYNCHRONOUS", font=font(25, True), fill=RED)
    labels = ["Request", "Payment\n0.8 s", "Restaurant\n0.5 s", "Inventory\n0.3 s", "Notify\n0.4 s", "Response\n~2 s"]
    for i, label in enumerate(labels):
        x = 55 + i*255
        box(d, (x, 245, x+205, 365), label, "#FDECEC" if i in (0, 5) else PALE, size=20)
        if i < len(labels)-1: arrow(d, (x+205, 305), (x+255, 305), color=RED)
    d.text((70, 495), "ASYNCHRONOUS", font=font(25, True), fill=NAVY)
    box(d, (80, 565, 300, 685), "Request", BLUE)
    box(d, (390, 565, 650, 685), "Save + publish", "#FFF0E8")
    box(d, (740, 565, 1020, 685), "202 Accepted\nin milliseconds", "#E8F5E9")
    arrow(d, (300, 625), (390, 625)); arrow(d, (650, 625), (740, 625))
    box(d, (1130, 505, 1510, 745), "Background workers\n\nPayment\nRestaurant + inventory\nNotifications", PALE, size=21)
    d.line((520, 565, 520, 470, 1130, 470, 1130, 505), fill=NAVY, width=4)
    d.polygon([(1130, 505), (1121, 489), (1139, 489)], fill=NAVY)
    d.text((755, 438), "queued background work", font=font(18), fill=NAVY)
    save(image, "before_after.png")


def sequence():
    image, d = canvas("Asynchronous order sequence", "The API response reaches the customer before any slow worker must finish.")
    names = ["Customer", "API", "PostgreSQL", "RabbitMQ", "Payment", "Restaurant", "Notification"]
    xs = [100, 320, 555, 800, 1035, 1260, 1490]
    for x, name in zip(xs, names):
        d.text((x-55, 175), name, font=font(20, True), fill=INK)
        d.line((x, 215, x, 820), fill="#C9CED4", width=2)
    events = [
        (100, 320, 270, "POST /orders", NAVY), (320, 555, 340, "save PENDING", NAVY),
        (320, 800, 410, "order.created", ORANGE), (320, 100, 480, "202 Accepted", NAVY),
        (800, 1035, 560, "created", NAVY), (800, 1260, 610, "created", NAVY),
        (800, 1490, 660, "created", NAVY), (1035, 800, 720, "order.paid", ORANGE),
        (800, 1490, 770, "paid", NAVY),
    ]
    for x1, x2, y, label, color in events:
        arrow(d, (x1, y), (x2, y), label, color)
    save(image, "sequence.png")


def deployment():
    image, d = canvas("Docker Compose deployment", "One application image runs five roles; infrastructure is health-gated.")
    box(d, (90, 235, 390, 405), "RabbitMQ 4\n5672 / 15672", BLUE)
    box(d, (90, 535, 390, 705), "PostgreSQL 17\n5432", "#F2EAFE")
    box(d, (90, 735, 390, 825), "Migration job", "#FFF0E8", size=22)
    box(d, (570, 340, 1010, 735),
        "Application roles\n\nAPI :8000\nPayment worker\nRestaurant worker\nNotification worker",
        "#FFF0E8", size=22)
    box(d, (1120, 315, 1510, 605), "Shared image\nfood-delivery-rabbitmq\n\nNon-root user\nPinned dependencies\nRestart policies", PALE, size=22)
    arrow(d, (570, 440), (390, 320), "AMQP")
    arrow(d, (570, 635), (390, 620), "SQL")
    arrow(d, (240, 735), (240, 705))
    arrow(d, (1010, 535), (1120, 535), "same image")
    save(image, "deployment.png")


if __name__ == "__main__":
    architecture(); before_after(); sequence(); deployment()
    print("rendered 4 diagrams in", OUT)
