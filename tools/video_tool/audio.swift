// Prints the peak sound level of every 40 ms of a video's audio between two times (macOS AVFoundation, no download).
// usage: swift audio.swift VIDEO FROM_SECONDS TO_SECONDS THRESHOLD   (only windows above THRESHOLD are printed; samples are 16-bit, so 0 to 32767)
import AVFoundation

let a = AVAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let from = Double(CommandLine.arguments[2])!
let to = Double(CommandLine.arguments[3])!
let threshold = Int(CommandLine.arguments[4])!
guard let tr = a.tracks(withMediaType: .audio).first else { print("no audio track"); exit(0) }
let r = try! AVAssetReader(asset: a)
let o = AVAssetReaderTrackOutput(track: tr, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM, AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false,
                                                             AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1])
r.add(o)
r.startReading()
var s = [Int16]()
while let b = o.copyNextSampleBuffer() {
    var l = 0
    var p: UnsafeMutablePointer<Int8>? = nil
    let bb = CMSampleBufferGetDataBuffer(b)!
    CMBlockBufferGetDataPointer(bb, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &l, dataPointerOut: &p)
    p!.withMemoryRebound(to: Int16.self, capacity: l / 2) { s.append(contentsOf: UnsafeBufferPointer(start: $0, count: l / 2)) }
}
let w = 640
var i = 0
while i + w <= s.count {
    let t = Double(i) / 16000
    if t >= from && t <= to {
        let pk = s[i..<i + w].map { abs(Int($0)) }.max()!
        if pk >= threshold { print(String(format: "%.2f %d", t, pk)) }
    }
    i += w
}
