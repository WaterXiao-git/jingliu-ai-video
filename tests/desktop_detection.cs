using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;
using Jingliu;

class DetectionTests {
    static void Check(bool ok, string name) { if (!ok) throw new Exception(name); Console.WriteLine("PASS " + name); }
    static void FileAt(string path) { Directory.CreateDirectory(Path.GetDirectoryName(path)); File.WriteAllText(path, "fixture"); }
    static int Main(string[] args) {
        string root = Path.GetFullPath(args[0]), comfy = Path.Combine(root, "中文 空格", "ComfyUI"), runtime = Path.Combine(root, ".runtime");
        Directory.CreateDirectory(runtime); Directory.CreateDirectory(Path.Combine(comfy, "models"));
        FileAt(Path.Combine(comfy, "main.py")); FileAt(Path.Combine(comfy, ".venv", "Scripts", "python.exe"));
        var disks = new[] { new DiskChoice { Root = "C:\\", Free = 100L << 30, System = true }, new DiskChoice { Root = "E:\\", Free = 60L << 30 } };
        var occupied = new HashSet<int> { 7861, 7862 };
        var json = new JavaScriptSerializer();
        File.WriteAllText(Path.Combine(runtime, "runtime.json"), json.Serialize(new { comfy = comfy, python = Path.Combine(comfy, ".venv", "Scripts", "python.exe"), ports = new { studio = 7871 }, region = "CN", ollama_binary = (string)null }));
        var existing = AutoSetup.Detect(null, "Z:\\已失效", new[] { root }, disks, occupied);
        Check(existing.existing && existing.target == runtime && existing.port == 7871 && !existing.writer, "stale saved path falls back to original deployment; preserves its port and features");
        var explicitPath = Path.Combine(root, "用户指定");
        var requested = AutoSetup.Detect(explicitPath, runtime, new[] { root }, disks, occupied);
        Check(!requested.existing && requested.target == explicitPath && requested.port == 7863, "explicit target wins over an existing deployment and occupied ports");
        var fresh = AutoSetup.Detect(null, null, new string[0], disks, occupied);
        Check(fresh.target == "E:\\JingliuRuntime" && fresh.writer && fresh.reuse == null && fresh.port == 7863, "fresh install selects sufficient non-system disk with writer");
        var small = AutoSetup.Detect(null, null, new string[0], new[] { new DiskChoice { Root = "E:\\", Free = 38L << 30 } }, occupied);
        Check(!small.writer, "35 GiB fits video but does not silently add a 45 GiB install");
        var insufficient = AutoSetup.Detect(null, null, new string[0], new[] { new DiskChoice { Root = "E:\\", Free = 1L << 30 } }, occupied);
        Check(insufficient.note.Contains("不足"), "insufficient disk is reported without claiming a ready installation");
        var reused = AutoSetup.Detect(null, null, new[] { Path.GetDirectoryName(comfy) }, disks, occupied);
        Check(reused.reuse == comfy && !reused.existing, "nearby ComfyUI with Chinese path is discovered without copying it");
        var interrupted = Path.Combine(root, "interrupted"); Directory.CreateDirectory(interrupted);
        File.WriteAllText(Path.Combine(interrupted, "desktop-plan.json"), json.Serialize(new { target = interrupted, reuse_comfy = (string)null, with_ollama = true, studio_port = 7861, region = "SG" }));
        var resumed = AutoSetup.Detect(null, interrupted, new string[0], disks, occupied);
        Check(resumed.target == interrupted && resumed.port == 7863 && resumed.writer && resumed.region == "SG", "interrupted install resumes in place and avoids occupied port");
        var fallback = AutoSetup.Detect(null, null, new[] { Path.GetDirectoryName(comfy) }, disks, occupied, false);
        Check(fallback.reuse == null && fallback.target == "E:\\JingliuRuntime", "incompatible ComfyUI can fall back to a separate installation");
        return 0;
    }
}
