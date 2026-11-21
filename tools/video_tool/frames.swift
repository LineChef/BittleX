// Writes one PNG per time step of a video, using macOS's own AVFoundation (no download).
// usage: swift frames.swift VIDEO OUTDIR STEP_SECONDS FROM_SECONDS TO_SECONDS
import AVFoundation
import AppKit

let a = AVAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let out = CommandLine.arguments[2]
let step = Double(CommandLine.arguments[3])!
var t = Double(CommandLine.arguments[4])!
let to = min(Double(CommandLine.arguments[5])!, CMTimeGetSeconds(a.duration))
guard let tr = a.tracks(withMediaType: .video).first else { print("no video track"); exit(1) }
print("fps", tr.nominalFrameRate, "duration", CMTimeGetSeconds(a.duration), "size", tr.naturalSize)
let g = AVAssetImageGenerator(asset: a)
g.appliesPreferredTrackTransform = true
g.requestedTimeToleranceBefore = .zero
g.requestedTimeToleranceAfter = .zero
var i = 0
while t < to {
    if let im = try? g.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil) {
        let r = NSBitmapImageRep(cgImage: im)
        try? r.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: String(format: "%@/f%04d.png", out, i)))
    }
    t += step
    i += 1
}
print("frames", i)
