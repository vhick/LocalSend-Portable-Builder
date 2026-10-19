using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Web.Script.Serialization;

[assembly: AssemblyTitle("LocalSend Portable Launcher")]
[assembly: AssemblyProduct("LocalSend Portable Community Package")]
[assembly: AssemblyDescription("Launch the official LocalSend app with preserved portable settings")]

internal static class LocalSendPortable
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateHardLink(string newFileName, string existingFileName, IntPtr securityAttributes);

    private static string QuoteArgument(string argument)
    {
        if (argument.Length > 0 && argument.IndexOfAny(new char[] {' ', '\t', '\n', '\v', '"'}) == -1)
            return argument;
        var b = new StringBuilder("\"");
        int n = 0;
        foreach (char c in argument)
        {
            if (c == '\\') { n++; continue; }
            if (c == '"') { b.Append('\\', n * 2 + 1); b.Append('"'); n = 0; continue; }
            b.Append('\\', n); n = 0; b.Append(c);
        }
        b.Append('\\', n * 2); b.Append('"');
        return b.ToString();
    }

    private static string LockName(string root)
    {
        using (SHA256 sha = SHA256.Create())
        {
            byte[] hash = sha.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(root).ToLowerInvariant()));
            return @"Local\LocalSendPortable-" + BitConverter.ToString(hash, 0, 12).Replace("-", "");
        }
    }

    private static void Warn(string message)
    {
        MessageBox.Show(message, "LocalSend Portable", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    // LocalSend v1.18.2 uses File.writeAsStringSync, which writes directly to the
    // existing settings.json. A hard link therefore persists every change into Data.
    // No admin privileges or scheduled copy-back are necessary on NTFS.
    private static bool PrepareSettings(string live, string saved, out bool linked)
    {
        linked = false;
        Directory.CreateDirectory(Path.GetDirectoryName(saved));
        if (File.Exists(live) && !File.Exists(saved))
        {
            // Existing settings from an older native portable ZIP: migrate first.
            File.Move(live, saved);
        }
        if (!File.Exists(saved)) File.WriteAllText(saved, "{}", new UTF8Encoding(false));
        if (File.Exists(live))
        {
            // A crash can leave the hard link behind. If content matches Data,
            // remove only the obsolete App link; never replace the Data file.
            if (ByteEquals(File.ReadAllBytes(live), File.ReadAllBytes(saved)))
                File.Delete(live);
            else
            {
            Warn("An existing settings.json was found in App\\LocalSend.\n\n" +
                 "The safe copy is in Data\\Settings. Close all LocalSend instances, back up both files, " +
                 "then remove only the obsolete App\\LocalSend\\settings.json. No file was overwritten.");
            return false;
            }
        }
        if (CreateHardLink(live, saved, IntPtr.Zero))
        {
            linked = true;
            return true;
        }
        // FAT/exFAT/other non-hard-link filesystems: safe copy fallback. This
        // cannot provide the same crash durability as an NTFS hard link.
        File.Copy(saved, live, false);
        return true;
    }

    private static bool SyncFallback(string source, string dest, string tempTarget)
    {
        // Reject partial/corrupt JSON before replacing good settings.
        byte[] data = File.ReadAllBytes(source);
        if (data.Length < 2) return false;
        string raw;
        try
        {
            raw = new UTF8Encoding(false, true).GetString(data);
            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = 20 * 1024 * 1024;
            if (!(serializer.DeserializeObject(raw) is System.Collections.IDictionary)) return false;
        }
        catch (ArgumentException) { return false; }
        File.WriteAllBytes(tempTarget, data);
        if (File.Exists(dest))
        {
            try { File.Replace(tempTarget, dest, null); }
            catch (PlatformNotSupportedException)
            {
                File.Copy(tempTarget, dest, true);
                File.Delete(tempTarget);
            }
            catch (IOException)
            {
                // Some FAT / exFAT volumes cannot atomically replace a file.
                File.Copy(tempTarget, dest, true);
                File.Delete(tempTarget);
            }
        }
        else File.Move(tempTarget, dest);
        return true;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string app = Path.Combine(root, @"App\LocalSend");
        string target = Path.Combine(app, "localsend_app.exe");
        string saved = Path.Combine(root, @"Data\Settings\settings.json");
        string live = Path.Combine(app, "settings.json");
        string temp = Path.Combine(root, @"Data\Temp");
        string received = Path.Combine(root, @"Data\Received Files");
        if (!File.Exists(target)) { Warn("LocalSend executable not found:\n" + target); return 2; }

        bool isFirst;
        using (Mutex mutex = new Mutex(true, LockName(root), out isFirst))
        {
            if (!isFirst)
            {
                Warn("This portable copy is already open. Use its existing tray icon/window.");
                return 3;
            }
            bool linked = false;
            try
            {
                Directory.CreateDirectory(temp);
                Directory.CreateDirectory(received);
                if (!PrepareSettings(live, saved, out linked)) return 4;
                var psi = new ProcessStartInfo(target);
                psi.WorkingDirectory = app;
                psi.UseShellExecute = false;
                psi.EnvironmentVariables["TEMP"] = temp;
                psi.EnvironmentVariables["TMP"] = temp;
                var argLine = new StringBuilder();
                foreach (string arg in args)
                {
                    if (argLine.Length != 0) argLine.Append(' ');
                    argLine.Append(QuoteArgument(arg));
                }
                psi.Arguments = argLine.ToString();
                using (Process process = Process.Start(psi))
                {
                    if (process == null) throw new InvalidOperationException("LocalSend did not start.");
                    // The tray icon can keep LocalSend alive after its window closes.
                    // Wait for actual exit rather than the disappearance of the window.
                    if (linked) process.WaitForExit();
                    else
                    {
                        // On FAT/exFAT where hard links aren't available, periodically
                        // save changed settings while the app is open and again at exit.
                        byte[] previous = File.ReadAllBytes(live);
                        while (!process.WaitForExit(1000))
                        {
                            try
                            {
                                byte[] current = File.ReadAllBytes(live);
                                if (!ByteEquals(previous, current))
                                {
                                    if (SyncFallback(live, saved, saved + ".incoming"))
                                        previous = current;
                                }
                            }
                            catch (IOException) { /* Retry at the next interval. */ }
                            catch (UnauthorizedAccessException) { /* Retry. */ }
                        }
                    }
                }
                return 0;
            }
            catch (Exception e)
            {
                Warn("Could not run LocalSend in portable mode:\n\n" + e.Message);
                return 1;
            }
            finally
            {
                // After process exit, remove only the launcher-created settings link
                // / working copy. Data/Settings/settings.json is the persistent source.
                try
                {
                    if (File.Exists(live))
                    {
                        if (linked || SyncFallback(live, saved, saved + ".incoming"))
                            File.Delete(live);
                        else
                            Warn("Settings did not pass validation. Please keep the App\\LocalSend\\settings.json file " +
                                 "as a recovery copy, and do not replace App until repaired.");
                    }
                }
                catch (Exception e)
                {
                    Warn("Settings cleanup could not finish. Keep App\\LocalSend\\settings.json " +
                         "and Data\\Settings\\settings.json and review before updating.\n\n" + e.Message);
                }
                // Do not clear Temp, received files, settings or other user data.
            }
        }
    }

    private static bool ByteEquals(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        return true;
    }
}
