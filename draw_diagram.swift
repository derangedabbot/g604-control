import AppKit

let W: CGFloat = 1240, H: CGFloat = 820
let img = NSImage(size: NSSize(width: W, height: H))
img.lockFocus()

// координаты считаем сверху вниз: ty(y) переводит в систему AppKit
func ty(_ y: CGFloat) -> CGFloat { H - y }

func text(_ s: String, _ x: CGFloat, top y: CGFloat, size: CGFloat = 19,
          weight: NSFont.Weight = .regular, color: NSColor = .white, wrap: CGFloat = 0) {
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color,
    ]
    if wrap > 0 {
        let h = (s as NSString).boundingRect(with: NSSize(width: wrap, height: 1000),
                                             options: [.usesLineFragmentOrigin],
                                             attributes: attrs).height
        (s as NSString).draw(in: NSRect(x: x, y: ty(y + h), width: wrap, height: h), withAttributes: attrs)
    } else {
        (s as NSString).draw(at: NSPoint(x: x, y: ty(y + size)), withAttributes: attrs)
    }
}

func badge(_ n: String, _ x: CGFloat, top y: CGFloat, tone: NSColor) {
    let r: CGFloat = 16
    tone.setFill()
    NSBezierPath(ovalIn: NSRect(x: x - r, y: ty(y + r), width: r * 2, height: r * 2)).fill()
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 17, weight: .bold),
        .foregroundColor: NSColor(calibratedWhite: 0.08, alpha: 1),
    ]
    let s = n as NSString
    let size = s.size(withAttributes: attrs)
    s.draw(at: NSPoint(x: x - size.width / 2, y: ty(y + size.height / 2)), withAttributes: attrs)
}

let amber = NSColor(calibratedRed: 0.98, green: 0.72, blue: 0.15, alpha: 1)
let teal = NSColor(calibratedRed: 0.35, green: 0.78, blue: 0.72, alpha: 1)
let dim = NSColor(calibratedWhite: 0.62, alpha: 1)

// фон
NSColor(calibratedWhite: 0.10, alpha: 1).setFill()
NSRect(x: 0, y: 0, width: W, height: H).fill()

text("G604 — карта кнопок", 60, top: 40, size: 30, weight: .semibold)
text("номер на схеме = номер строки в списке приложения", 60, top: 80, size: 17, color: dim)

// ================= вид сверху =================
text("вид сверху", 60, top: 120, size: 17, color: dim)

let bx: CGFloat = 150, bw: CGFloat = 290, by: CGFloat = 160, bh: CGFloat = 540
NSColor(calibratedWhite: 0.20, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: bx, y: ty(by + bh), width: bw, height: bh),
             xRadius: 135, yRadius: 135).fill()
NSColor(calibratedWhite: 0.27, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: bx + 12, y: ty(by + bh - 12), width: bw - 24, height: bh - 24),
             xRadius: 125, yRadius: 125).fill()

let cx = bx + bw / 2

// разделитель левой/правой кнопки
NSColor(calibratedWhite: 0.12, alpha: 1).setStroke()
let split = NSBezierPath()
split.move(to: NSPoint(x: cx, y: ty(by + 220)))
split.line(to: NSPoint(x: cx, y: ty(by + 80)))
split.lineWidth = 3
split.stroke()

// колесо
NSColor(calibratedWhite: 0.12, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: cx - 25, y: ty(by + 210), width: 50, height: 92),
             xRadius: 23, yRadius: 23).fill()

// две кнопки DPI за колесом
NSBezierPath(roundedRect: NSRect(x: cx - 13, y: ty(by + 300), width: 26, height: 52),
             xRadius: 11, yRadius: 11).fill()
NSBezierPath(roundedRect: NSRect(x: cx - 13, y: ty(by + 360), width: 26, height: 46),
             xRadius: 11, yRadius: 11).fill()

// метки
badge("1", bx + 55, top: by + 90, tone: amber)
badge("2", bx + bw - 55, top: by + 90, tone: amber)
badge("3", cx + 80, top: by + 175, tone: amber)
badge("10", cx + 95, top: by + 290, tone: amber)
badge("11", cx + 95, top: by + 350, tone: amber)
badge("12", cx - 95, top: by + 290, tone: amber)
badge("13", cx - 95, top: by + 350, tone: amber)

// стрелки наклона
NSColor(calibratedWhite: 0.55, alpha: 1).setStroke()
for (x1, x2) in [(cx - 70, cx - 35), (cx + 35, cx + 70)] {
    let p = NSBezierPath()
    p.move(to: NSPoint(x: x1, y: ty(by + 240)))
    p.line(to: NSPoint(x: x2, y: ty(by + 240)))
    p.lineWidth = 2
    p.stroke()
}

// ================= вид сбоку =================
text("вид сбоку (шесть боковых кнопок)", 560, top: 120, size: 17, color: dim)

let sx: CGFloat = 590, sw: CGFloat = 250, sy: CGFloat = 180, sh: CGFloat = 440
NSColor(calibratedWhite: 0.20, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: sx - 30, y: ty(sy + sh), width: sw + 30, height: sh),
             xRadius: 80, yRadius: 80).fill()
NSColor(calibratedWhite: 0.27, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: sx - 12, y: ty(sy + sh - 18), width: sw, height: sh - 36),
             xRadius: 70, yRadius: 70).fill()

let sides = [("4", 0, 0), ("5", 0, 1), ("6", 0, 2), ("7", 1, 0), ("8", 1, 1), ("9", 1, 2)]
for (num, col, row) in sides {
    let x = sx + CGFloat(col) * 118
    let y = sy + 40 + CGFloat(row) * 130
    NSColor(calibratedWhite: 0.13, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: x, y: ty(y + 78), width: 96, height: 78),
                 xRadius: 20, yRadius: 20).fill()
    badge(num, x + 48, top: y + 39, tone: teal)
}

// ================= легенда =================
let legend: [(String, String, NSColor)] = [
    ("1", "левая кнопка", amber),
    ("2", "правая кнопка", amber),
    ("3", "нажатие колеса", amber),
    ("4–9", "боковые кнопки (слева на корпусе)", teal),
    ("10–11", "кнопки DPI за колесом", amber),
    ("12", "наклон колеса влево", amber),
    ("13", "наклон колеса вправо", amber),
    ("14–15", "служебные (на схеме не показаны)", dim),
    ("16", "резерв", dim),
]
var ly: CGFloat = 180
text("что где", 900, top: 120, size: 17, color: dim)
for (num, desc, tone) in legend {
    text(num, 900, top: ly, size: 19, weight: .semibold, color: tone)
    text(desc, 970, top: ly, size: 18, color: NSColor(calibratedWhite: 0.85, alpha: 1), wrap: 260)
    ly += 44
}

text("Порядок 4–9 на боковой панели может отличаться:\nнажмите кнопку и сверьтесь с тем, что приходит\nв систему — так вы точно узнаете номер.", 900, top: ly + 20,
     size: 16, color: dim, wrap: 280)

img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: "diagram.png"))
print("diagram.png готов")
