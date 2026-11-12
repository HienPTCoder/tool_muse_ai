// Tách người khỏi ảnh bằng Apple Vision (chạy trên máy, không cần mạng): person_mask <ảnh vào> <mask.png ra>
import Foundation
import Vision
import CoreImage
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let img = CIImage(contentsOf: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: person_mask in.jpg out.png\n".data(using: .utf8)!); exit(2)
}
let req = VNGeneratePersonSegmentationRequest()
req.qualityLevel = .accurate
req.outputPixelFormat = kCVPixelFormatType_OneComponent8
try VNImageRequestHandler(ciImage: img).perform([req])
guard let buf = req.results?.first?.pixelBuffer else { FileHandle.standardError.write("no person\n".data(using: .utf8)!); exit(1) }
var mask = CIImage(cvPixelBuffer: buf)
mask = mask.transformed(by: CGAffineTransform(scaleX: img.extent.width / mask.extent.width, y: img.extent.height / mask.extent.height))
let ctx = CIContext()
guard let cg = ctx.createCGImage(mask, from: img.extent) else { exit(1) }
let rep = NSBitmapImageRep(cgImage: cg)
try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
