using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.NetworkInformation;
using System.Web.Script.Serialization;

namespace Jingliu {
    internal sealed class DiskChoice {
        internal string Root;
        internal long Free;
        internal bool System;
    }
    internal sealed class SetupChoice {
        public string target;
        public string reuse;
        public int port;
        public bool writer;
        public bool existing;
        public string note;
        public string region = "CN";
    }
    // Bounded discovery: inspect known names near the EXE, never crawl a user's disks.
    internal static class AutoSetup {
        const long GiB = 1073741824L;
        static bool Comfy(string path) {
            return !String.IsNullOrEmpty(path) && File.Exists(Path.Combine(path, "main.py")) &&
                Directory.Exists(Path.Combine(path, "models")) && File.Exists(Path.Combine(path, ".venv", "Scripts", "python.exe"));
        }
        static SetupChoice Existing(string path) {
            try {
                var config = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(path, "runtime.json")));
                var comfy = (string)config["comfy"];
                int port = Convert.ToInt32(((Dictionary<string, object>)config["ports"])["studio"]);
                if (!File.Exists((string)config["python"]) || !File.Exists(Path.Combine(comfy, "main.py")) ||
                    !Directory.Exists(Path.Combine(comfy, "models")) || port < 1024 || port > 65535) return null;
                return new SetupChoice { target = Path.GetFullPath(path), reuse = comfy, port = port,
                    existing = true, writer = config["ollama_binary"] != null, region = (string)config["region"], note = "已找到原有部署，直接复用模型与项目。" };
            } catch { return null; }
        }
        internal static SetupChoice Detect(string requested, string saved, IEnumerable<string> roots, IEnumerable<DiskChoice> disks, HashSet<int> occupied, bool allowReuse = true) {
            var nearby = roots.Where(p => !String.IsNullOrWhiteSpace(p)).Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            // Explicit paths are authoritative, including an interrupted installation.
            if (!String.IsNullOrWhiteSpace(requested)) {
                var installed = Existing(requested);
                if (installed != null) return installed;
            } else {
                var candidates = new List<string>();
                if (!String.IsNullOrWhiteSpace(saved)) candidates.Add(saved);
                foreach (string root in nearby) {
                    candidates.Add(Path.Combine(root, ".runtime"));
                    candidates.Add(Path.Combine(root, "JingliuRuntime"));
                    candidates.Add(root);
                }
                foreach (string candidate in candidates) { var installed = Existing(candidate); if (installed != null) return installed; }
                // Resume a previously planned install without choosing another disk and downloading twice.
                try {
                    var previous = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(saved, "desktop-plan.json")));
                    if (String.Equals(Path.GetFullPath((string)previous["target"]), Path.GetFullPath(saved), StringComparison.OrdinalIgnoreCase)) {
                        int previousPort = Convert.ToInt32(previous["studio_port"]);
                        if (previousPort < 1024 || previousPort > 65535 || previousPort == 8193 || previousPort == 11435 || occupied.Contains(previousPort)) previousPort = 7861;
                        while (occupied.Contains(previousPort) || previousPort == 8193 || previousPort == 11435) previousPort++;
                        if (previousPort > 65535) throw new IOException("没有可用端口");
                        string previousReuse = previous["reuse_comfy"] as string;
                        if (previousReuse == null || (allowReuse && Comfy(previousReuse))) return new SetupChoice { target = Path.GetFullPath(saved), reuse = previousReuse,
                            port = previousPort, writer = (bool)previous["with_ollama"], region = (string)previous["region"], existing = false, note = "找到上次安装计划，沿用同一目录并重新检测，可复用已下载资源。" };
                    }
                } catch { }
            }
            string reuse = null;
            foreach (string root in nearby) {
                foreach (string candidate in new[] { Path.Combine(root, "ComfyUI"), Path.Combine(root, "ComfyUI_windows_portable", "ComfyUI"), root }) {
                    if (allowReuse && Comfy(candidate)) { reuse = candidate; break; }
                }
                if (reuse != null) break;
            }
            var available = disks.OrderBy(d => d.System).ThenByDescending(d => d.Free).ToList();
            long minimum = (reuse == null ? 35 : 3) * GiB;
            var selected = available.FirstOrDefault(d => d.Free >= minimum);
            bool enough = selected != null;
            if (selected == null) selected = available.OrderByDescending(d => d.Free).FirstOrDefault();
            string target = !String.IsNullOrWhiteSpace(requested) ? Path.GetFullPath(requested) :
                selected != null ? Path.Combine(selected.Root, "JingliuRuntime") : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "JingliuRuntime");
            var targetDisk = available.FirstOrDefault(d => String.Equals(Path.GetPathRoot(target), Path.GetPathRoot(d.Root), StringComparison.OrdinalIgnoreCase));
            bool writer = targetDisk != null && targetDisk.Free >= (reuse == null ? 45 : 13) * GiB;
            int port = 7861;
            while (port <= 65535 && (occupied.Contains(port) || port == 8193 || port == 11435)) port++;
            if (port > 65535) throw new IOException("没有可用的工作台端口，请稍后重试。");
            return new SetupChoice { target = target, reuse = reuse, port = port, writer = writer, existing = false,
                note = (!enough ? "磁盘空间可能不足，检测将给出具体要求。" : "已自动选择运行目录和空闲工作台端口。") +
                    (reuse == null ? "将准备新环境。" : "发现已有 ComfyUI，将先检查兼容性；不会修改其环境。") +
                    (writer ? "包含本地 AI 编剧。" : "暂不加装可选编剧，以节省空间。") };
        }
        internal static SetupChoice Local(string requested, bool allowReuse = true) {
            var roots = new List<string>();
            foreach (string start in new[] { Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location), Environment.CurrentDirectory }) {
                var dir = new DirectoryInfo(start);
                for (int i = 0; i < 4 && dir != null; i++, dir = dir.Parent) roots.Add(dir.FullName);
            }
            roots.Add(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments));
            var disks = new List<DiskChoice>();
            foreach (var drive in DriveInfo.GetDrives()) {
                try {
                    if (!drive.IsReady || drive.DriveType != DriveType.Fixed) continue;
                    disks.Add(new DiskChoice { Root = drive.RootDirectory.FullName, Free = drive.AvailableFreeSpace,
                        System = String.Equals(drive.Name, Path.GetPathRoot(Environment.SystemDirectory), StringComparison.OrdinalIgnoreCase) });
                    roots.Add(drive.RootDirectory.FullName);
                } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
            string saved = null;
            try { saved = (string)new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Jingliu", "desktop-settings.json")))["target"]; } catch { }
            var occupied = new HashSet<int>(IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Select(p => p.Port));
            return Detect(requested, saved, roots, disks, occupied, allowReuse);
        }
    }
}
