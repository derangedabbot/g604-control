import AppKit

let size: CGFloat = 1024
let img = NSImage(size: NSSize(width: size, height: size))
img.lockFocus()

// фон: тёмный скруглённый квадрат
NSColor(calibratedRed: 0.11, green: 0.11, blue: 0.13, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size),
             xRadius: 220, yRadius: 220).fill()

// силуэт мыши
NSColor(calibratedWhite: 0.92, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 382, y: 250, width: 260, height: 620),
             xRadius: 130, yRadius: 130).fill()

// «шов» между кнопками и колесо
NSColor(calibratedRed: 0.11, green: 0.11, blue: 0.13, alpha: 1).setFill()
NSBezierPath(ovalIn: NSRect(x: 487, y: 690, width: 50, height: 110)).fill()
NSBezierPath(rect: NSRect(x: 511, y: 620, width: 2, height: 240)).fill()

// подпись
let text = "G604" as NSString
let attrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 150, weight: .semibold),
    .foregroundColor: NSColor(calibratedWhite: 0.92, alpha: 1),
]
let ts = text.size(withAttributes: attrs)
text.draw(at: NSPoint(x: (size - ts.width) / 2, y: 90), withAttributes: attrs)

img.unlockFocus()

let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: "icon-1024.png"))
print("icon-1024.png готов")
