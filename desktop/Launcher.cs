using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("镜流 · AI 短剧启动中心")]
[assembly: AssemblyVersion("0.1.5.0")]
[assembly: AssemblyFileVersion("0.1.5.0")]

namespace Jingliu {
    internal static class Core {
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        internal static string StateRoot { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Jingliu"); } }
        internal static string Q(string value) {
            var result = new StringBuilder("\""); int slash = 0;
            foreach (char c in value) {
                if (c == '\\') { slash++; continue; }
                if (c == '"') result.Append('\\', slash * 2 + 1).Append(c);
                else result.Append('\\', slash).Append(c);
                slash = 0;
            }
            return result.Append('\\', slash * 2).Append('"').ToString();
        }
        internal static Dictionary<string, object> Read(string path) { return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)); }
        internal static string DisplayText(string path) { return File.ReadAllText(path, Encoding.UTF8).Replace("\r\n", "\n").Replace("\n", Environment.NewLine); }
        internal static string Hash(Stream stream) { using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
        internal static string FileHash(string path) { using (var stream = File.OpenRead(path)) return Hash(stream); }
        internal static string Inside(string root, string relative) {
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string path = Path.GetFullPath(Path.Combine(prefix, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("启动包路径越界。");
            return path;
        }
        internal static bool ValidPayload(string root, Dictionary<string, object> manifest) {
            foreach (var item in manifest) {
                string file = Inside(root, item.Key);
                if (!File.Exists(file) || FileHash(file) != (string)item.Value) return false;
            }
            return true;
        }
        internal static string EnsurePayload(string requested) {
            string root = Path.GetFullPath(requested ?? Path.Combine(StateRoot, "app", BuildInfo.Digest.Substring(0, 16)));
            using (var gate = new Mutex(false, "Local\\JingliuPayload-" + BuildInfo.Digest.Substring(0, 16))) {
                bool owned = false;
                try {
                    try { owned = gate.WaitOne(TimeSpan.FromSeconds(60)); } catch (AbandonedMutexException) { owned = true; }
                    if (!owned) throw new IOException("另一个镜流正在准备启动包，请稍后再试。");
                    using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("Jingliu.Payload")) {
                        if (resource == null || Hash(resource) != BuildInfo.Digest) throw new IOException("EXE 内置启动包校验失败，请重新获取文件。");
                        resource.Position = 0;
                        using (var zip = new ZipArchive(resource, ZipArchiveMode.Read)) {
                            Dictionary<string, object> manifest;
                            using (var reader = new StreamReader(zip.GetEntry("payload-manifest.json").Open(), Encoding.UTF8)) manifest = Json.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                            if (Directory.Exists(root)) {
                                if (ValidPayload(root, manifest)) return root;
                                throw new IOException("启动包缓存不完整，请移走这个缓存目录后重新打开：" + root);
                            }
                            string parent = Path.GetDirectoryName(root); Directory.CreateDirectory(parent);
                            string stage = root + ".extract-" + Guid.NewGuid().ToString("N"); Directory.CreateDirectory(stage);
                            try {
                                foreach (ZipArchiveEntry entry in zip.Entries) {
                                    string path = Inside(stage, entry.FullName);
                                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                                    using (var source = entry.Open()) using (var output = new FileStream(path, FileMode.CreateNew)) source.CopyTo(output);
                                }
                                if (!ValidPayload(stage, manifest)) throw new IOException("启动包文件校验失败。");
                                Directory.Move(stage, root);
                            } finally {
                                // stage is created by this extraction, never an arbitrary user directory.
                                if (Directory.Exists(stage) && Path.GetFullPath(stage).StartsWith(root + ".extract-", StringComparison.OrdinalIgnoreCase)) Directory.Delete(stage, true);
                            }
                        }
                    }
                    return root;
                } finally { if (owned) gate.ReleaseMutex(); }
            }
        }
        internal static ProcessStartInfo PowerShell(string root, string script, IEnumerable<string> arguments) {
            var command = new StringBuilder("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ").Append(Q(Inside(root, script)));
            foreach (string value in arguments) command.Append(' ').Append(Q(value));
            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"),
                Arguments = command.ToString(), WorkingDirectory = root, UseShellExecute = false,
                CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            start.EnvironmentVariables.Remove("PYTHONHOME"); start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables["PYTHONUTF8"] = "1"; start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            return start;
        }
        internal static string Workspace(string target) {
            string path = Path.GetFullPath(Path.Combine(target, "studio-data")).TrimEnd('\\').ToLowerInvariant();
            using (var bytes = new MemoryStream(Encoding.UTF8.GetBytes(path))) return Hash(bytes);
        }
        internal static bool Ready(string target) {
            try {
                var config = Read(Path.Combine(target, "runtime.json"));
                var ports = (Dictionary<string, object>)config["ports"];
                var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + ports["studio"] + "/api/identity");
                request.Proxy = null; request.Timeout = 500; request.ReadWriteTimeout = 500;
                using (var response = request.GetResponse()) using (var reader = new StreamReader(response.GetResponseStream())) {
                    var identity = Json.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                    return (string)identity["app"] == "jingliu" && (string)identity["workspace"] == Workspace(target);
                }
            } catch (WebException) { return false; } catch (IOException) { return false; }
              catch (ArgumentException) { return false; } catch (KeyNotFoundException) { return false; }
        }
        internal static async Task<bool> WaitReady(string target, bool wantReady) {
            for (int i = 0; i < (wantReady ? 180 : 80); i++) {
                bool ready = await Task.Run(() => Ready(target));
                if (ready == wantReady) return true;
                await Task.Delay(250);
            }
            return false;
        }
        internal static List<string> LaunchArgs(string target, bool stop, bool noBrowser) {
            var args = new List<string> { "-Target", Path.GetFullPath(target) };
            if (stop) args.Add("-Stop"); if (noBrowser) args.Add("-NoBrowser"); return args;
        }
        internal static int Command(string root, string target, bool stop, bool noBrowser) {
            using (var process = Process.Start(PowerShell(root, "deploy/launch.ps1", LaunchArgs(target, stop, noBrowser)))) {
                // Read both pipes concurrently so diagnostic output cannot deadlock.
                var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
                process.WaitForExit(); Task.WaitAll(output, error);
                if (process.ExitCode != 0) throw new IOException(error.Result + output.Result);
            }
            if (!WaitReady(target, !stop).GetAwaiter().GetResult()) throw new IOException("等待工作台状态超时，请查看运行目录中的 launcher.log。");
            return 0;
        }
    }

    internal sealed class LauncherForm : Form {
        readonly string root;
        readonly TextBox target = new TextBox { Name = "runtime", Dock = DockStyle.Fill };
        readonly TextBox reuse = new TextBox { Name = "reuse", Dock = DockStyle.Fill };
        readonly TextBox region = new TextBox { Text = "CN", Width = 65, CharacterCasing = CharacterCasing.Upper, MaxLength = 2 };
        readonly NumericUpDown port = new NumericUpDown { Minimum = 1024, Maximum = 65535, Value = 7861, Width = 80 };
        readonly CheckBox writer = new CheckBox { Text = "同时安装本地 AI 编剧（额外约 6.3 GB 下载）", AutoSize = true };
        readonly CheckBox license = new CheckBox { Text = "已阅读 H3 模型许可，确认实际使用地区，并同意本次安装计划", AutoSize = true };
        readonly RichTextBox log = new RichTextBox { ReadOnly = true, Dock = DockStyle.Fill, BackColor = Color.FromArgb(17, 20, 31), ForeColor = Color.FromArgb(209, 214, 230), BorderStyle = BorderStyle.None, Font = new Font("Microsoft YaHei UI", 9), DetectUrls = false };
        readonly Label status = new Label { Text = "选择运行目录，从检查开始。", Dock = DockStyle.Fill, AutoSize = true, ForeColor = Color.FromArgb(185, 165, 255) };
        readonly Label space = new Label { AutoSize = true, ForeColor = Color.Silver, Dock = DockStyle.Fill };
        readonly Label detected = new Label { AutoSize = true, ForeColor = Color.Silver, Dock = DockStyle.Fill };
        readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill, Height = 5, Visible = false, Style = ProgressBarStyle.Marquee };
        readonly Button planButton, installButton, openButton, stopButton, cancelButton;
        Dictionary<string, object> plan;
        string signature;
        bool busy;
        bool cancelled;
        Process currentProcess;
        bool initializing = true;
        readonly bool autoOpen;
        readonly string explicitTarget;
        bool autoSelected = true;

        internal LauncherForm(string appRoot, string requestedTarget, bool manage) {
            root = appRoot; autoOpen = !manage; explicitTarget = requestedTarget;
            Text = "镜流 · AI 短剧启动中心";
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleDimensions = new SizeF(96F, 96F); AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(24, 27, 40); ForeColor = Color.FromArgb(238, 240, 248);
            ClientSize = new Size(1000, 730); MinimumSize = new Size(900, 690);
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(26, 20, 26, 20), ColumnCount = 1, RowCount = 10 };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 78));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 72));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 88));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 12));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); Controls.Add(layout);
            var heading = new Panel { Dock = DockStyle.Fill };
            using (var image = Assembly.GetExecutingAssembly().GetManifestResourceStream("Jingliu.Logo")) {
                if (image != null) heading.Controls.Add(new PictureBox { Image = new Bitmap(image), SizeMode = PictureBoxSizeMode.Zoom, Size = new Size(58, 58), Location = new Point(0, 2) });
            }
            heading.Controls.Add(new Label { Text = "镜流 · 本地创作，从这里开始", AutoSize = true, Font = new Font(Font.FontFamily, 19, FontStyle.Bold), Location = new Point(73, 0) });
            heading.Controls.Add(new Label { Text = "自动检测 → 一键安装 → 开始创作    /    Windows EXE 预览版 " + BuildInfo.Version, AutoSize = true, ForeColor = Color.Silver, Location = new Point(76, 42) });
            layout.Controls.Add(heading, 0, 0);
            var paths = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 4 };
            paths.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 148)); paths.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); paths.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 102));
            paths.RowStyles.Add(new RowStyle(SizeType.Absolute, 36)); paths.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            paths.RowStyles.Add(new RowStyle(SizeType.Absolute, 36)); paths.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
            paths.Controls.Add(new Label { Text = "模型与项目目录", AutoSize = true }, 0, 0); paths.Controls.Add(target, 1, 0);
            paths.Controls.Add(Button("选择目录", () => Browse(target, true)), 2, 0);
            paths.Controls.Add(new Label { Text = "已有 ComfyUI", AutoSize = true }, 0, 1); paths.Controls.Add(reuse, 1, 1);
            paths.Controls.Add(Button("复用目录", () => Browse(reuse, false)), 2, 1);
            var existing = Button("选择已有部署…", SelectRuntime);
            paths.Controls.Add(existing, 1, 2);
            paths.Controls.Add(new Label { Text = "可选；选择包含 runtime.json 的目录即可接入已有部署。", AutoSize = true, ForeColor = Color.Silver }, 1, 3);
            paths.Visible = false;
            layout.Controls.Add(paths, 0, 1);
            var location = new Panel { Dock = DockStyle.Fill };
            var advanced = Button("高级设置 ▾", delegate { });
            advanced.Dock = DockStyle.Right;
            location.Controls.Add(space); location.Controls.Add(advanced);
            layout.Controls.Add(location, 0, 2);
            var options = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
            options.Controls.Add(new Label { Text = "实际地区", AutoSize = true, Padding = new Padding(0, 5, 0, 0) }); options.Controls.Add(region);
            options.Controls.Add(new Label { Text = "工作台端口", AutoSize = true, Padding = new Padding(15, 5, 0, 0) }); options.Controls.Add(port);
            options.Controls.Add(writer); options.Visible = false; layout.Controls.Add(options, 0, 3);
            advanced.Click += delegate {
                bool show = !paths.Visible; paths.Visible = options.Visible = show;
                float scale; using (var graphics = CreateGraphics()) scale = graphics.DpiY / 96F;
                layout.RowStyles[1].Height = show ? 138 * scale : 0; layout.RowStyles[3].Height = show ? 36 * scale : 0;
                advanced.Text = show ? "收起设置 ▴" : "高级设置 ▾";
            };
            layout.Controls.Add(detected, 0, 4);
            layout.Controls.Add(license, 0, 5);
            var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = true };
            planButton = Button("重新检测", Prepare); installButton = Button("一键安装并打开", Install);
            openButton = Button("打开工作台", Open); stopButton = Button("关闭后台", Stop);
            cancelButton = Button("停止当前操作", Cancel);
            actions.Controls.AddRange(new Control[] { planButton, installButton, openButton, stopButton, Button("模型许可", ShowLicense), Button("帮助 / 在线方案", Help), cancelButton });
            layout.Controls.Add(actions, 0, 6); layout.Controls.Add(status, 0, 7); layout.Controls.Add(progress, 0, 8); layout.Controls.Add(log, 0, 9);
            var choice = AutoSetup.Local(requestedTarget);
            target.Text = choice.target; reuse.Text = choice.reuse ?? ""; port.Value = choice.port; writer.Checked = choice.writer; region.Text = choice.region;
            target.TextChanged += delegate { InvalidatePlan(); UpdateSpace(); };
            target.Leave += delegate { LoadExisting(); };
            reuse.TextChanged += delegate { InvalidatePlan(); UpdateSpace(); };
            region.TextChanged += delegate { InvalidatePlan(); UpdateSpace(); };
            writer.CheckedChanged += delegate { InvalidatePlan(); UpdateSpace(); };
            port.ValueChanged += delegate { InvalidatePlan(); UpdateSpace(); };
            license.CheckedChanged += delegate { UpdateButtons(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) { e.Cancel = true; MessageBox.Show(this, "检测、安装或启动正在进行，请等待当前操作结束后关闭窗口。", "镜流"); } };
            initializing = false; LoadExisting(); UpdateSpace(); UpdateButtons();
            Append("欢迎使用镜流。" + choice.note + "\n首次使用会自动检测电脑并准备计划，无需填写目录和端口。阅读许可、核对实际地区与预算后，勾选同意并点“一键安装并打开”。\n高级设置可更改自动选择；国内下载不代表程序能判断你实际身处的地区。\n生成时可在工作台的任务队列查看进度，或进入星光等待室。");
            // Font assignment can reset the design DPI before controls are added.
            AutoScaleDimensions = new SizeF(96F, 96F);
            Shown += delegate {
                if (choice.existing) { if (autoOpen) BeginInvoke(new Action(Open)); }
                else BeginInvoke(new Action(Prepare));
            };
        }
        Button Button(string text, Action action) {
            var button = new Button { Text = text, AutoSize = true, Height = 34, FlatStyle = FlatStyle.Flat, Padding = new Padding(9, 3, 9, 3), Margin = new Padding(0, 2, 8, 2), ForeColor = ForeColor, BackColor = Color.FromArgb(42, 42, 61) };
            button.FlatAppearance.BorderColor = Color.FromArgb(88, 78, 117); button.Click += delegate { action(); }; return button;
        }
        string ConfigPath { get { return Path.Combine(target.Text.Trim(), "runtime.json"); } }
        string PlanPath { get { return Path.Combine(Path.GetFullPath(target.Text.Trim()), "desktop-plan.json"); } }
        string Signature { get { return target.Text.Trim() + "|" + reuse.Text.Trim() + "|" + region.Text + "|" + port.Value + "|" + writer.Checked; } }
        void InvalidatePlan() { if (initializing) return; autoSelected = false; plan = null; signature = null; license.Checked = false; UpdateButtons(); }
        void UpdateButtons() {
            bool canInstall = plan != null && signature == Signature && (bool)((Dictionary<string, object>)((Dictionary<string, object>)plan["report"])["evaluation"])["can_install"];
            planButton.Enabled = !busy; installButton.Enabled = !busy && canInstall && license.Checked;
            cancelButton.Enabled = busy && currentProcess != null && !cancelled;
            openButton.Enabled = stopButton.Enabled = !busy && File.Exists(ConfigPath);
            license.Visible = installButton.Visible = !File.Exists(ConfigPath) || plan != null;
            target.Enabled = reuse.Enabled = region.Enabled = writer.Enabled = port.Enabled = license.Enabled = !busy;
        }
        void UpdateSpace() {
            try {
                var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(target.Text.Trim())));
                space.Text = String.Format("目标磁盘 {0} 剩余 {1:0.0} GiB · {2}", drive.Name, drive.AvailableFreeSpace / 1073741824.0, File.Exists(ConfigPath) ? "已找到部署配置，可直接打开" : "先检查预算，再开始下载");
            } catch { space.Text = "请选择可访问的本地磁盘目录。"; }
            detected.Text = "运行目录：" + target.Text + "\n" + (String.IsNullOrWhiteSpace(reuse.Text) ? "新建视频环境" : "复用：" + reuse.Text) +
                " · " + (writer.Checked ? "包含本地编剧" : "暂不加装编剧") + "\n实际地区：" + region.Text + "（默认 CN / 中国，请核对） · 工作台端口：" + port.Value;
            license.Text = "我已阅读模型许可，确认实际使用地区为 " + region.Text + "，并同意显示的安装计划";
        }
        void LoadExisting() {
            try {
                var config = Core.Read(ConfigPath); initializing = true;
                reuse.Text = (string)config["comfy"]; region.Text = (string)config["region"];
                port.Value = Convert.ToInt32(((Dictionary<string, object>)config["ports"])["studio"]);
                writer.Checked = config["ollama_binary"] != null;
                status.Text = "已找到部署，点“打开工作台”即可。";
            } catch { } finally { initializing = false; UpdateSpace(); UpdateButtons(); }
        }
        void Browse(TextBox field, bool runtime) {
            if (busy) return;
            using (var dialog = new FolderBrowserDialog { Description = runtime ? "选择模型与项目的运行目录（已有部署选择包含 runtime.json 的目录）" : "选择已有 ComfyUI 目录", SelectedPath = Directory.Exists(field.Text) ? field.Text : "" }) {
                if (dialog.ShowDialog(this) == DialogResult.OK) { field.Text = dialog.SelectedPath; if (runtime) LoadExisting(); }
            }
        }
        void SelectRuntime() {
            if (busy) return;
            using (var dialog = new OpenFileDialog { Title = "选择已有部署的 runtime.json", Filter = "镜流部署配置|runtime.json", CheckFileExists = true }) {
                if (dialog.ShowDialog(this) == DialogResult.OK) { target.Text = Path.GetDirectoryName(dialog.FileName); LoadExisting(); }
            }
        }
        void Append(string text) {
            if (IsDisposed || String.IsNullOrEmpty(text)) return;
            if (InvokeRequired) { BeginInvoke(new Action<string>(Append), text); return; }
            if (log.TextLength > 90000) { log.Select(0, 30000); log.SelectedText = ""; }
            log.AppendText(text + Environment.NewLine); log.SelectionStart = log.TextLength; log.ScrollToCaret();
        }
        List<string> SetupArgs(string mode) {
            var args = new List<string> { "-Mode", mode, "-Target", Path.GetFullPath(target.Text.Trim()), "-Region", region.Text, "-Port", port.Value.ToString() };
            if (!String.IsNullOrWhiteSpace(reuse.Text)) { args.Add("-ReuseComfy"); args.Add(Path.GetFullPath(reuse.Text.Trim())); }
            if (writer.Checked) args.Add("-WithOllama"); return args;
        }
        async Task<bool> Operation(string label, string script, List<string> args) {
            if (busy) return false; busy = true; cancelled = false; progress.Visible = true; status.Text = label; UpdateButtons();
            try {
                Directory.CreateDirectory(Core.StateRoot);
                using (var file = new StreamWriter(Path.Combine(Core.StateRoot, "desktop.log"), true, Encoding.UTF8))
                using (var process = new Process { StartInfo = Core.PowerShell(root, script, args) }) {
                    object gate = new object();
                    DataReceivedEventHandler receive = delegate(object sender, DataReceivedEventArgs e) {
                        if (e.Data == null) return;
                        lock (gate) { file.WriteLine(e.Data); file.Flush(); } Append(e.Data);
                    };
                    process.OutputDataReceived += receive; process.ErrorDataReceived += receive;
                    process.Start(); currentProcess = process; UpdateButtons(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
                    await Task.Run(() => process.WaitForExit());
                    if (process.ExitCode != 0) throw new IOException("操作未完成（退出码 " + process.ExitCode + "），请查看下方详情。");
                }
                status.Text = "操作完成。"; return true;
            } catch (Exception error) {
                Append(cancelled ? "当前操作已停止。已校验的下载会保留，可在同一目录重新准备计划后继续。" : error.Message);
                status.Text = cancelled ? "当前操作已停止。" : "操作未完成，请查看详情后重试。"; return false;
            }
            finally { currentProcess = null; busy = false; progress.Visible = false; UpdateButtons(); }
        }
        async void Cancel() {
            Process owned = currentProcess;
            if (!busy || owned == null || cancelled || owned.HasExited) return;
            if (MessageBox.Show(this, "停止本次检测或安装？未完成的验证会中断，已校验的模型和可续传文件会保留。", "停止当前操作", MessageBoxButtons.YesNo) != DialogResult.Yes) return;
            if (!busy || currentProcess != owned || owned.HasExited) return;
            cancelled = true; UpdateButtons();
            try {
                int pid = owned.Id;
                await Task.Run(() => {
                    if (owned.HasExited) return;
                    using (var kill = Process.Start(new ProcessStartInfo {
                        FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe"),
                        Arguments = "/PID " + pid + " /T /F", UseShellExecute = false, CreateNoWindow = true
                    })) kill.WaitForExit();
                });
            } catch (Exception error) { Append(error.Message); }
        }
        void SaveTarget() {
            Directory.CreateDirectory(Core.StateRoot);
            File.WriteAllText(Path.Combine(Core.StateRoot, "desktop-settings.json"), Core.Json.Serialize(new { target = Path.GetFullPath(target.Text.Trim()) }), Encoding.UTF8);
        }
        async void Prepare() {
            try {
                var args = SetupArgs("Plan"); args.Add("-AllowPythonBootstrap"); args.Add("-PlanFile"); args.Add(PlanPath);
                signature = Signature; plan = null; license.Checked = false;
                if (!await Operation("正在检测并准备安装计划；尚未下载模型…", "deploy/setup.ps1", args)) return;
                plan = Core.Read(PlanPath); SaveTarget();
                var report = (Dictionary<string, object>)plan["report"];
                var evaluation = (Dictionary<string, object>)report["evaluation"];
                Append("\n—— 电脑检测结果 ——");
                foreach (Dictionary<string, object> check in (IEnumerable)evaluation["checks"]) {
                    string state = (string)check["state"];
                    object actual = check["actual"];
                    string detail = actual is IEnumerable && !(actual is string) ? Core.Json.Serialize(actual) : Convert.ToString(actual);
                    Append((state == "ok" ? "✓ " : "! ") + check["item"] + "：" + detail + "；要求 " + check["required"] + "；" + check["action"]);
                }
                if (autoSelected && !String.IsNullOrWhiteSpace(reuse.Text) && !File.Exists(ConfigPath)) {
                    bool incompatible = false;
                    foreach (Dictionary<string, object> check in (IEnumerable)evaluation["checks"])
                        if (((string)check["item"] == "复用目录" || (string)check["item"] == "复用软件版本") && (string)check["state"] != "ok") incompatible = true;
                    if (incompatible) {
                        var fresh = AutoSetup.Local(explicitTarget, false);
                        initializing = true;
                        try { target.Text = fresh.target; reuse.Text = ""; port.Value = fresh.port; writer.Checked = fresh.writer; }
                        finally { initializing = false; }
                        plan = null; license.Checked = false; UpdateSpace(); UpdateButtons();
                        Append("已有 ComfyUI 不适配当前视频模型，保留它不变，自动改为准备独立环境并重新检查空间。" );
                        Prepare(); return;
                    }
                }
                Append(String.Format("\n已知资源下载约 {0:0.0} GB，另预估 Python 依赖 {1} GiB；目标盘需空闲 {2:0.0} GiB。", Convert.ToDouble(plan["known_download_bytes_baseline"]) / 1e9, plan["python_wheel_download_estimate_gib"], Convert.ToDouble(plan["minimum_target_free_bytes"]) / 1073741824.0));
                status.Text = (bool)evaluation["can_install"] ? "检测通过。请阅读模型许可、确认地区和计划，勾选后安装。" : "当前条件未通过，请按检测结果调整，或查看在线方案。";
                UpdateButtons();
            } catch (Exception error) { plan = null; Append(error.Message); status.Text = "请检查路径和检测结果。"; UpdateButtons(); }
        }
        async void Install() {
            if (plan == null || signature != Signature || !license.Checked) return;
            try {
                var args = SetupArgs("Install"); args.Add("-Approve"); args.Add((string)plan["approval"]); args.Add("-AllowPythonBootstrap"); args.Add("-NoStart");
                if (await Operation("正在部署并做 4 步短镜头功能验收；正式生成默认 20 步…", "deploy/setup.ps1", args)) {
                    SaveTarget(); LoadExisting(); status.Text = "部署和出片验证完成，正在打开工作台。"; Open();
                }
            } catch (Exception error) { Append(error.Message); }
        }
        async void Open() {
            if (busy) return;
            try {
                SaveTarget();
                if (!await Operation("正在打开工作台…", "deploy/launch.ps1", Core.LaunchArgs(target.Text.Trim(), false, false))) return;
                busy = true; UpdateButtons(); progress.Visible = true;
                status.Text = "正在等待工作台就绪，模型随后按需加载…";
                bool ready = await Core.WaitReady(target.Text.Trim(), true);
                status.Text = ready ? "工作台已就绪。关闭此窗口或网页后，后台任务仍会继续。" : "等待超时，请查看运行目录中的 launcher.log。";
            } catch (Exception error) { Append(error.Message); }
            finally { busy = false; progress.Visible = false; UpdateButtons(); }
        }
        async void Stop() {
            if (busy) return;
            if (MessageBox.Show(this, "关闭后台会中断尚未完成的生成任务。现在关闭？", "关闭镜流后台", MessageBoxButtons.YesNo) != DialogResult.Yes) return;
            if (!await Operation("正在关闭镜流管理的后台服务…", "deploy/launch.ps1", Core.LaunchArgs(target.Text.Trim(), true, false))) return;
            busy = true; UpdateButtons();
            bool stopped = await Core.WaitReady(target.Text.Trim(), false);
            busy = false; UpdateButtons(); status.Text = stopped ? "后台已关闭。" : "服务仍在运行；若不是本启动器启动，请回到原启动入口关闭。";
        }
        void ShowLicense() {
            try {
                using (var viewer = new Form { Text = "MiniMax H3 模型许可 · 完整原文", Size = new Size(830, 650), StartPosition = FormStartPosition.CenterParent, Font = Font }) {
                    var text = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical,
                        Text = Core.DisplayText(Path.Combine(root, "docs", "MINIMAX-H3-LICENSE.txt")) };
                    viewer.Controls.Add(text); viewer.AutoScaleMode = AutoScaleMode.Dpi; viewer.AutoScaleDimensions = new SizeF(96F, 96F);
                    viewer.Shown += delegate { text.SelectionStart = 0; text.SelectionLength = 0; };
                    viewer.ShowDialog(this);
                }
            } catch (Exception error) { Append(error.Message); }
        }
        void Help() {
            var help = new Form { Text = "镜流 · 使用帮助与在线方案", Size = new Size(780, 590), StartPosition = FormStartPosition.CenterParent, Font = Font };
            var text = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical, Text = Core.DisplayText(Path.Combine(root, "docs", "desktop.md")) };
            var links = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 90, Padding = new Padding(10), AutoScroll = true };
            var platforms = Core.Read(Path.Combine(root, "deploy", "platforms.yaml"));
            foreach (Dictionary<string, object> item in (IEnumerable)platforms["platforms"]) {
                string url = (string)item["url"];
                var link = new LinkLabel { Text = (string)item["name"], AutoSize = true, Margin = new Padding(10) };
                link.LinkClicked += delegate { if (new Uri(url).Scheme == "https") Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); };
                links.Controls.Add(link);
            }
            help.Controls.Add(text); help.Controls.Add(links); help.AutoScaleMode = AutoScaleMode.Dpi; help.AutoScaleDimensions = new SizeF(96F, 96F); help.ShowDialog(this);
        }
    }

    internal static class Program {
        static string Option(string[] args, string name) { int index = Array.IndexOf(args, name); return index >= 0 && index + 1 < args.Length ? args[index + 1] : null; }
        [STAThread] static int Main(string[] args) {
            bool cli = Array.IndexOf(args, "--start") >= 0 || Array.IndexOf(args, "--stop") >= 0 || Array.IndexOf(args, "--self-test") >= 0 || Array.IndexOf(args, "--detect") >= 0;
            try {
                string detection = Option(args, "--detect");
                if (detection != null) {
                    File.WriteAllText(detection, Core.Json.Serialize(AutoSetup.Local(Option(args, "--target"))), new UTF8Encoding(false)); return 0;
                }
                string root = Core.EnsurePayload(Option(args, "--app-root"));
                string target = Option(args, "--target");
                string report = Option(args, "--self-test");
                if (report != null) {
                    var rows = new Dictionary<string, object> { {"version", BuildInfo.Version}, {"payload", root}, {"payload_sha256", BuildInfo.Digest}, {"python_required_for_exe", false}, {"zip_traversal_rejected", false} };
                    try { Core.Inside(root, "../outside"); } catch (IOException) { rows["zip_traversal_rejected"] = true; }
                    if (target != null) rows["workspace_ready"] = Core.Ready(target);
                    var command = Core.PowerShell(root, "deploy/launch.ps1", Core.LaunchArgs("D:\\测试 目录\\", false, true));
                    rows["launch_arguments"] = command.Arguments;
                    rows["required_files_present"] = File.Exists(Path.Combine(root, "studio", "studio.py")) && File.Exists(Path.Combine(root, "deploy", "vendor", "ComfyUI-783ab7282af1.zip"));
                    File.WriteAllText(report, Core.Json.Serialize(rows), new UTF8Encoding(false)); return 0;
                }
                if (cli) {
                    if (target == null || !File.Exists(Path.Combine(target, "runtime.json"))) throw new IOException("请通过 --target 指定已有部署目录。");
                    return Core.Command(root, Path.GetFullPath(target), Array.IndexOf(args, "--stop") >= 0,
                                        Array.IndexOf(args, "--stop") >= 0 || Array.IndexOf(args, "--no-browser") >= 0);
                }
                Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new LauncherForm(root, target, Array.IndexOf(args, "--manage") >= 0)); return 0;
            } catch (Exception error) {
                if (!cli) MessageBox.Show(error.Message, "镜流启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                try { Directory.CreateDirectory(Core.StateRoot); File.AppendAllText(Path.Combine(Core.StateRoot, "desktop-error.log"), error + Environment.NewLine, Encoding.UTF8); } catch { }
                return 1;
            }
        }
    }
}
