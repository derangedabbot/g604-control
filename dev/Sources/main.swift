import Foundation
import CoreGraphics
import ApplicationServices

// Прототип-логгер: пишет в файл все события мыши (и клавиш), чтобы понять,
// что именно приходит от кнопок Logitech G604.

let logPath = NSString(string: "~/Cursor/g604-control/events.log").expandingTildeInPath
let fm = FileManager.default
try? fm.createDirectory(atPath: (logPath as NSString).deletingLastPathComponent,
                        withIntermediateDirectories: true)
if !fm.fileExists(atPath: logPath) { fm.createFile(atPath: logPath, contents: nil) }
let handle = FileHandle(forWritingAtPath: logPath)
handle?.seekToEndOfFile()

let stamp: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm:ss.SSS"
    return f
}()

func write(_ s: String) {
    print(s)
    fflush(stdout)
    handle?.write((s + "\n").data(using: .utf8)!)
}

func mods(_ flags: CGEventFlags) -> String {
    var m: [String] = []
    if flags.contains(.maskShift) { m.append("shift") }
    if flags.contains(.maskControl) { m.append("ctrl") }
    if flags.contains(.maskAlternate) { m.append("opt") }
    if flags.contains(.maskCommand) { m.append("cmd") }
    if flags.contains(.maskSecondaryFn) { m.append("fn") }
    return m.isEmpty ? "-" : m.joined(separator: "+")
}

func describe(_ type: CGEventType) -> String {
    switch type {
    case .leftMouseDown: return "leftDown"
    case .leftMouseUp: return "leftUp"
    case .rightMouseDown: return "rightDown"
    case .rightMouseUp: return "rightUp"
    case .otherMouseDown: return "otherDown"
    case .otherMouseUp: return "otherUp"
    case .scrollWheel: return "scroll"
    case .keyDown: return "keyDown"
    case .keyUp: return "keyUp"
    case .tapDisabledByTimeout: return "tapDisabledByTimeout"
    case .tapDisabledByUserInput: return "tapDisabledByUserInput"
    default: return "type\(type.rawValue)"
    }
}

let callback: CGEventTapCallBack = { _, type, event, _ in
    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        write("\(stamp.string(from: Date())) ТАП ОТКЛЮЧЁН системой: \(describe(type))")
        return Unmanaged.passUnretained(event)
    }
    let ts = stamp.string(from: Date())
    switch type {
    case .otherMouseDown, .otherMouseUp, .leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp:
        let btn = event.getIntegerValueField(.mouseEventButtonNumber)
        let click = event.getIntegerValueField(.mouseEventClickState)
        write("\(ts) \(describe(type))\tbutton=\(btn)\tclick=\(click)\tmods=\(mods(event.flags))")
    case .scrollWheel:
        let dy = event.getIntegerValueField(.scrollWheelEventDeltaAxis1)
        let dx = event.getIntegerValueField(.scrollWheelEventDeltaAxis2)
        let pdy = event.getIntegerValueField(.scrollWheelEventPointDeltaAxis1)
        let pdx = event.getIntegerValueField(.scrollWheelEventPointDeltaAxis2)
        if dx != 0 || dy != 0 {
            write("\(ts) scroll\tv=\(dy)\th=\(dx)\tpv=\(pdy)\tph=\(pdx)\tmods=\(mods(event.flags))")
        }
    case .keyDown:
        let code = event.getIntegerValueField(.keyboardEventKeycode)
        let repeatCount = event.getIntegerValueField(.keyboardEventAutorepeat)
        if repeatCount == 0 {
            write("\(ts) keyDown\tkeycode=\(code)\tmods=\(mods(event.flags))")
        }
    default:
        break
    }
    return Unmanaged.passUnretained(event)
}

let types: [CGEventType] = [.otherMouseDown, .otherMouseUp, .leftMouseDown, .leftMouseUp,
                            .rightMouseDown, .rightMouseUp, .scrollWheel, .keyDown]
var mask: CGEventMask = 0
for t in types { mask |= (1 << t.rawValue) }

let axOptions = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
let trusted = AXIsProcessTrustedWithOptions(axOptions)
write("--- старт \(Date()) ---")
write("Универсальный доступ: \(trusted ? "выдан" : "НЕ выдан (нужно разрешить в Системных настройках)")")

guard let tap = CGEvent.tapCreate(tap: .cgSessionEventTap,
                                  place: .headInsertEventTap,
                                  options: .defaultTap,
                                  eventsOfInterest: mask,
                                  callback: callback,
                                  userInfo: nil) else {
    write("НЕ УДАЛОСЬ создать перехват событий. Почти всегда это отсутствие разрешения «Универсальный доступ».")
    exit(2)
}

let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
CGEvent.tapEnable(tap: tap, enable: true)
write("Перехват включён. Нажимайте кнопки мыши.")
CFRunLoopRun()
